"""REPL 入口与命令行分派：交互走 REPL，非交互单轮执行后退出。"""

import json
import os
import shutil
import sys
from pathlib import Path
from typing import List, Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import FileHistory

from ..config.loader import ConfigError, load_config
from ..config.paths import HISTORY_FILE
from ..config.settings import load_settings
from ..context.params import compact_threshold
from ..model.catalog import Ambiguous, Resolved
from ..runtime.logging_setup import setup_logging
from ..sessions.query import ensure_session_name, find_session, latest_session_for_cwd, remember_session
from .args import Options, parse_args
from .commands import configure, handle_command
from .run import JsonEmitter, PlainEmitter, stream_run
from .state import AppState
from .ui import GLYPH, PT_STYLE, context_bar, reset_cursor_color, set_cursor_color

# 退出码：0 成功，1 运行失败/会话不存在，2 用法或配置问题，130 被中断。
EXIT_OK = 0
EXIT_RUN_FAILED = 1
EXIT_USAGE = 2
EXIT_CANCELLED = 130


def apply_options(state: AppState, options: Options) -> None:
    """把启动参数落到状态上：模型、权限模式、续接的会话。"""
    changed = False
    if options.model:
        result = state.catalog.resolve(options.model)
        if isinstance(result, Ambiguous):
            names = "、".join(ref.display for ref in result.candidates)
            _fail(f"模型引用有歧义：{options.model} 命中 {names}，请加渠道前缀。")
        if not isinstance(result, Resolved):
            _fail(f"没有匹配的模型：{options.model}")
        state.provider, state.model_id = result.ref.provider, result.ref.model_id
        changed = True
    if options.permission and options.permission != state.mode:
        state.mode = options.permission
        changed = True
    if changed:
        state.rebuild_agent()

    if options.continue_session:
        session = latest_session_for_cwd(state.agent, str(Path.cwd()), state.settings)
        if session is None:
            _fail(f"当前目录没有历史会话：{Path.cwd()}")
        state.session_id = session.session_id
    elif options.resume:
        session = find_session(state.agent, options.resume, state.settings)
        if session is None:
            _fail(f"没有匹配的会话：{options.resume}")
        state.session_id = session.session_id


def _user_id(state: AppState) -> str:
    return str(state.settings.get("memory.user_id"))


def _approval_strategy(state: AppState) -> str:
    return str(state.settings.get("boundary.command_approval"))


def _fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(EXIT_USAGE)


def read_message(options: Options) -> Optional[str]:
    """非交互模式的消息：位置参数优先，其次 stdin。"""
    if options.message:
        return options.message
    if sys.stdin.isatty():
        return None
    return sys.stdin.read().strip() or None


def run_once(state: AppState, message: str, output: str, allow_shell: bool = False) -> int:
    """非交互执行一轮，按输出形态渲染并给出退出码。"""
    if output == "json":
        emitter: PlainEmitter | JsonEmitter = JsonEmitter(allow_shell=allow_shell)
    else:
        emitter = PlainEmitter(allow_shell=allow_shell)
    remember_session(str(Path.cwd()), state.session_id)
    summary = stream_run(
        state.agent, message, state.session_id, state.approved, emitter,
        user_id=_user_id(state), strategy=_approval_strategy(state),
        channel=state.provider,
    )
    if output == "json":
        print(json.dumps({
            "type": "result",
            "session_id": state.session_id,
            "content": summary.get("content", ""),
            "tokens": summary.get("tokens", 0),
            "duration_s": round(float(summary.get("duration", 0) or 0), 3),
            "error": bool(summary.get("error")),
            "cancelled": bool(summary.get("cancelled")),
        }, ensure_ascii=False), flush=True)
    if summary.get("cancelled"):
        return EXIT_CANCELLED
    return EXIT_RUN_FAILED if summary.get("error") else EXIT_OK


def main(argv: Optional[List[str]] = None) -> None:
    settings = load_settings()
    for warning in settings.warnings:
        print(warning, file=sys.stderr)
    options = parse_args(str(settings.get("boundary.default_mode")), argv)
    setup_logging(settings)

    # 首次启动或配置不完整：交互模式进入向导，非交互模式直接报错。
    # 配置文件存在却读不出来时一律报错退出，绝不进向导（保存会覆盖原文件）。
    try:
        config = load_config(settings)
    except ConfigError as exc:
        print(f"{GLYPH['fail']} {exc}", file=sys.stderr)
        print("修好配置文件后再启动；程序不会覆盖它。", file=sys.stderr)
        raise SystemExit(EXIT_USAGE)
    if config is None:
        if not options.interactive:
            print("尚未配置渠道，先运行 aaa 进入配置向导。", file=sys.stderr)
            raise SystemExit(EXIT_USAGE)
        print("首次启动，先完成渠道配置。")
        try:
            config = configure(None, settings)
        except (EOFError, KeyboardInterrupt):
            print("\n已取消配置。")
            return
        if config is None:
            print("未完成配置，退出。")
            return

    state = AppState.start(config, settings)
    apply_options(state, options)

    if not options.interactive:
        message = read_message(options)
        if not message:
            raise SystemExit("非交互模式需要提示词：aaa -p \"...\" 或从 stdin 传入。")
        sys.exit(run_once(state, message, options.output, options.allow_shell))

    # 底部状态条：模型、会话、当前目录；跟随输入区重绘。
    def toolbar():
        cwd = os.getcwd()
        home = str(Path.home())
        if cwd == home:
            cwd = "~"
        elif cwd.startswith(home + os.sep):
            cwd = "~" + cwd[len(home):]
        cwd_width = int(settings.get("ui.toolbar_width"))
        if len(cwd) > cwd_width:
            cwd = "…" + cwd[-(cwd_width - 1):]
        parts = [
            ("class:toolbar.dim", f" session {state.session_id} "),
            ("class:toolbar.dim", " · "),
            ("class:toolbar.model", f" {state.model_ref.display} "),
            ("class:toolbar.dim", " · "),
            ("class:toolbar.dim", f" {state.mode} "),
            ("class:toolbar.dim", " · "),
            ("class:toolbar.dim", f" {cwd} "),
        ]
        if state.context_tokens:
            window = state.window()
            prefix = f" session {state.session_id}  ·  {state.model_ref.display}  ·  {cwd} "
            width = shutil.get_terminal_size((100, 24)).columns - len(prefix) - 8
            bar = context_bar(
                int(state.context_tokens), int(window),
                max(int(settings.get("ui.bar_min_width")),
                    min(width, int(settings.get("ui.bar_max_width")))),
                compact_threshold(int(window), settings),
            )
            parts.append(("class:toolbar.dim", " · " + bar))
        return FormattedText(parts)

    print("输入 /help 查看命令，Ctrl-D 退出。\n")
    set_cursor_color("#7fd1ff")
    named: set = set()

    session = PromptSession(
        history=FileHistory(str(HISTORY_FILE)),
        auto_suggest=AutoSuggestFromHistory(),
        completer=state.completer,
        complete_while_typing=True,
        style=PT_STYLE,
        bottom_toolbar=toolbar,
    )

    pending = options.message
    while True:
        if pending is not None:
            text, pending = pending.strip(), None
            if not text:
                continue
            print(GLYPH["prompt"] + " " + text)
        else:
            try:
                text = session.prompt(FormattedText([("class:prompt", GLYPH["prompt"] + " ")])).strip()
            except KeyboardInterrupt:
                continue
            except EOFError:
                print()
                reset_cursor_color()
                break

        if not text:
            continue

        if text == "/exit":
            reset_cursor_color()
            break
        if handle_command(state, text):
            session.completer = state.completer
            continue

        remember_session(str(Path.cwd()), state.session_id)
        summary = stream_run(
            state.agent, text, state.session_id, state.approved,
            strategy=_approval_strategy(state), channel=state.provider,
        )
        if summary.get("context_tokens"):
            state.context_tokens = summary["context_tokens"]
        channel, model = state.selection()
        ensure_session_name(
            state.agent, channel, model,
            state.session_id, text, named, GLYPH["title"], state.settings,
        )

    # 退出时清掉进程内的 model 引用；Key 已持久化在 secret.yaml（0600）。
    state.agent.model.api_key = None
