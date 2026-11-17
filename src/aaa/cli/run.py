"""一轮运行的流式输出、HITL 审批与事件格式化。

事件循环与渲染分开：`HumanEmitter` 是交互 REPL，`PlainEmitter` / `JsonEmitter`
给非交互模式用，三者共用同一套事件与审批逻辑。
"""

import json
import logging
import sys
import time
from typing import Dict, Optional, Set

import questionary
from agno.agent import Agent
from agno.run.agent import (
    ModelRequestCompletedEvent,
    ModelRequestStartedEvent,
    RunCancelledEvent,
    RunCompletedEvent,
    RunContentEvent,
    RunErrorEvent,
    RunPausedEvent,
    ToolCallCompletedEvent,
    ToolCallErrorEvent,
    ToolCallStartedEvent,
)

from ..boundary.policy import APPROVAL_ALWAYS, needs_approval, signature
from ..boundary.danger import danger_reason
from .ui import GLYPH, UI_STYLE, StatusLine

# 运行期异常落 ~/.aaa/logs/aaa.log（logging_setup 给 "aaa" 挂了文件 handler）。
logger = logging.getLogger("aaa")


def format_tool(name: str, args) -> str:
    """把工具调用压成一行，参数过长时截断。"""
    if not args:
        return str(name)
    text = json.dumps(args, ensure_ascii=False)
    if len(text) > 80:
        text = text[:77] + "..."
    return f"{name} {text}"


def _tool_duration(tool, started: Optional[float]) -> float:
    """优先用 Agno 记录的耗时，没有则用本地计时。"""
    metrics = getattr(tool, "metrics", None)
    duration = getattr(metrics, "duration", None) if metrics is not None else None
    if duration:
        return float(duration)
    return time.monotonic() - started if started else 0.0


class HumanEmitter:
    """交互渲染：状态行、流式正文、工具行。"""

    def __init__(self) -> None:
        self.status = StatusLine()
        self.line_open = False

    def _line(self, text: str) -> None:
        self.status.clear()
        if self.line_open:
            sys.stdout.write("\n")
            self.line_open = False
        print(text)

    def event(self, kind: str, **data) -> None:
        if kind == "model_start":
            self.status.update(f"  \x1b[2m{GLYPH['working']} Working…\x1b[0m")
        elif kind == "content":
            self.status.clear()
            if not self.line_open:
                sys.stdout.write("\n")
                self.line_open = True
            sys.stdout.write(str(data["text"]))
            sys.stdout.flush()
        elif kind == "tool_start":
            line = f"  {GLYPH['dot']} {format_tool(data['tool'], data.get('args'))}"
            self._line(f"\x1b[2m{line}\x1b[0m" if sys.stdout.isatty() else line)
        elif kind == "tool_done":
            self._line(f"  {GLYPH['ok']} {data['tool']} {data['duration']:.1f}s")
        elif kind == "tool_error":
            self._line(f"  {GLYPH['fail']} {data['tool']} {data['duration']:.1f}s · {data.get('error') or 'error'}")
        elif kind == "error":
            self._line(f"  {GLYPH['fail']} {data.get('message') or 'run error'}")
        elif kind == "cancelled":
            self._line(f"  {GLYPH['fail']} 已取消")

    def ask_approval(self, name: str, args) -> bool:
        detail = json.dumps(args, ensure_ascii=False)[:140] if args else ""
        self._line(f"  ? {name} {detail}".rstrip())
        try:
            return bool(questionary.confirm("允许执行？", default=False, style=UI_STYLE).ask())
        except (EOFError, KeyboardInterrupt):
            return False

    def close(self) -> None:
        self.status.clear()
        if self.line_open:
            sys.stdout.write("\n")
            self.line_open = False


class PlainEmitter:
    """非交互正文输出：只把助手回复写到 stdout，工具活动进日志。"""

    def __init__(self, allow_shell: bool = False) -> None:
        self.allow_shell = allow_shell

    def event(self, kind: str, **data) -> None:
        if kind == "content":
            sys.stdout.write(str(data["text"]))
            sys.stdout.flush()
        elif kind == "tool_error":
            logger.warning("tool failed: %s · %s", data["tool"], data.get("error"))
        elif kind == "error":
            logger.error("run error: %s", data.get("message"))

    def ask_approval(self, name: str, args) -> bool:
        if self.allow_shell and name == "run_shell_command":
            logger.info("非交互模式按 --allow-shell 放行工具 %s", name)
            return True
        logger.warning("非交互模式无法确认工具 %s，已拒绝", name)
        return False

    def close(self) -> None:
        sys.stdout.write("\n")
        sys.stdout.flush()


class JsonEmitter:
    """非交互结构化输出：每行一个事件，末行由调用方补 result。"""

    def __init__(self, allow_shell: bool = False) -> None:
        self.allow_shell = allow_shell

    def event(self, kind: str, **data) -> None:
        record = {"type": kind}
        for key, value in data.items():
            if key == "tool":
                continue
            if key == "duration":
                record["duration_s"] = round(float(value), 3)
            else:
                record[key] = value
        if "tool" in data:
            record["tool"] = data["tool"]
        print(json.dumps(record, ensure_ascii=False), flush=True)

    def ask_approval(self, name: str, args) -> bool:
        if self.allow_shell and name == "run_shell_command":
            print(json.dumps(
                {"type": "confirm_approved", "tool": name, "args": args}, ensure_ascii=False
            ), flush=True)
            return True
        print(json.dumps(
            {"type": "confirm_required", "tool": name, "args": args}, ensure_ascii=False
        ), flush=True)
        return False

    def close(self) -> None:
        pass


def approve_requirements(
    requirements, approved: Set[str], emitter, strategy: str = APPROVAL_ALWAYS
) -> None:
    """逐个处理 HITL 要求。

    已批准过的同签名直接放行；`dangerous` 策略下未命中危险规则的一次调用
    也直接放行（记日志）；其余交给渲染器决定。
    """
    for requirement in requirements:
        tool = getattr(requirement, "tool_execution", None)
        name = getattr(tool, "tool_name", "tool")
        args = getattr(tool, "tool_args", None)
        key = signature(name, args)
        if key in approved:
            requirement.confirm()
            continue
        if not needs_approval(name, args, strategy):
            logger.info(
                "审批策略 %s：自动放行 %s（%s）", strategy, name, danger_reason(name, args) or "未命中危险规则"
            )
            requirement.confirm()
            continue
        if emitter.ask_approval(name, args):
            approved.add(key)
            requirement.confirm()
        else:
            requirement.reject("用户拒绝")


def stream_run(
    agent: Agent,
    text: str,
    session_id: str,
    approved: Optional[Set[str]] = None,
    emitter=None,
    user_id: Optional[str] = None,
    strategy: str = APPROVAL_ALWAYS,
    channel: str = "",
) -> Dict:
    """流式执行一轮；处理 Agno HITL 暂停并在批准后继续。

    `user_id` 决定记忆归属；不传时 Agno 落到 `"default"`。
    `strategy` 决定「需要确认的工具」这一次要不要真的问人；默认每条都问。
    `channel` 写进 run metadata，供用量账本按 (渠道, 模型) 计价——Agno 自己只记
    provider 类名，无法区分同一模型的多个渠道。
    """
    render = emitter or HumanEmitter()
    approved = approved if approved is not None else set()
    tool_start: Dict[str, float] = {}
    summary: Dict = {}
    run_id: Optional[str] = None
    pieces: list = []

    try:
        metadata = {"channel": channel} if channel else None
        events = agent.run(
            text, session_id=session_id, user_id=user_id, stream=True, stream_events=True,
            metadata=metadata,
        )
        while True:
            paused = None
            for event in events:
                if run_id is None:
                    run_id = getattr(event, "run_id", None)
                if isinstance(event, ModelRequestStartedEvent):
                    render.event("model_start")
                elif isinstance(event, RunContentEvent) and event.content:
                    pieces.append(str(event.content))
                    render.event("content", text=str(event.content))
                elif isinstance(event, ToolCallStartedEvent) and event.tool:
                    name = getattr(event.tool, "tool_name", "tool") or "tool"
                    tool_start[name] = time.monotonic()
                    render.event("tool_start", tool=name, args=getattr(event.tool, "tool_args", None))
                elif isinstance(event, ToolCallCompletedEvent) and event.tool:
                    name = getattr(event.tool, "tool_name", "tool") or "tool"
                    render.event(
                        "tool_done",
                        tool=name,
                        duration=_tool_duration(event.tool, tool_start.get(name)),
                    )
                elif isinstance(event, ToolCallErrorEvent) and event.tool:
                    name = getattr(event.tool, "tool_name", "tool") or "tool"
                    render.event(
                        "tool_error",
                        tool=name,
                        duration=_tool_duration(event.tool, tool_start.get(name)),
                        error=event.error,
                    )
                elif isinstance(event, ModelRequestCompletedEvent):
                    if getattr(event, "input_tokens", None):
                        summary["context_tokens"] = event.input_tokens
                elif isinstance(event, RunPausedEvent):
                    paused = event
                    break
                elif isinstance(event, RunCompletedEvent):
                    metrics = getattr(event, "metrics", None)
                    if metrics is not None:
                        summary["tokens"] = getattr(metrics, "total_tokens", 0) or 0
                        summary["duration"] = getattr(metrics, "duration", 0) or 0
                elif isinstance(event, RunErrorEvent):
                    logger.error("run error: %s", event.content or "run error")
                    summary["error"] = True
                    render.event("error", message=event.content)
                elif isinstance(event, RunCancelledEvent):
                    logger.warning("run cancelled")
                    summary["cancelled"] = True
                    render.event("cancelled")

            if paused is None:
                break

            requirements = paused.requirements or []
            approve_requirements(requirements, approved, render, strategy)
            events = agent.continue_run(
                run_id=paused.run_id,
                requirements=requirements,
                # 从 run_id 继续必须带 session_id，否则 Agno 直接拒绝。
                session_id=session_id,
                user_id=user_id,
                stream=True,
                stream_events=True,
                metadata=metadata,
            )
    except KeyboardInterrupt:
        if run_id:
            try:
                agent.cancel_run(run_id=run_id)
            except Exception:
                pass
        summary["cancelled"] = True
        render.event("cancelled")
    except Exception as exc:
        logger.exception("run failed")
        summary["error"] = True
        render.event("error", message=str(exc))
    finally:
        render.close()
    summary["content"] = "".join(pieces)
    return summary
