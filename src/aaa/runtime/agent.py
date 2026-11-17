"""Agent 装配：把 Provider、Tools、Context、Boundary、Memory 与持久化拼成 Agent。"""

from pathlib import Path
from typing import Any, Protocol

from agno.agent import Agent
from agno.compaction import Compaction
from agno.db.sqlite import SqliteDb
from agno.memory import MemoryManager

from ..boundary.policy import PolicySource, resolve_policy
from ..config.paths import DATA_DIR, DB_FILE
from ..context.params import compaction_budget, compact_threshold, history_runs
from ..model.catalog import Catalog
from ..tools.assemble import POWERSHELL_HINT, SHELL_HINT, build_tools, tool_names


class SettingsLike(Protocol):
    def get(self, path: str) -> Any: ...


def tools_for_mode(mode: str, settings: SettingsLike, policy: PolicySource = resolve_policy) -> list:
    """权限模式与工具能力的合并点。

    `policy` 是替换点：默认用 `boundary.resolve_policy`；沙箱或插件可以传入
    自己的实现，返回不同的能力清单与隔离范围，而不用改工具或运行时。
    """
    resolved = policy(mode)
    return build_tools(
        resolved.capabilities,
        root=resolved.isolation.file_root,
        confirm_tools=resolved.confirm_tools,
        file_caps={
            "max_file_lines": int(settings.get("tools.file_max_lines")),
            "max_file_length": int(settings.get("tools.file_max_length")),
        },
        weather_timeout=int(settings.get("tools.weather_timeout")),
        shell_timeout=int(settings.get("tools.shell_timeout")),
        shell_output_bytes=int(settings.get("tools.shell_output_bytes")),
        shell_tail=int(settings.get("tools.shell_tail")),
    )


def build_agent(
    catalog: Catalog,
    provider: str,
    model_id: str,
    mode: str,
    settings: SettingsLike,
) -> Agent:
    """构造 Agent 实例：Provider + Tools + 会话持久化 + 原生压缩 + 记忆。

    切换模型、权限模式或相关配置都重建 Agent，不做原地改：Agno 只在构造时
    把 fallback_models 转成 fallback_config，原地改两个字段迟早漏掉一个。
    """
    model = catalog.require(provider, model_id)[1]
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    fallback_models = catalog.fallbacks(provider, model_id)
    compaction = Compaction(
        compact_at_tokens=compact_threshold(model.context_window, settings),
        uncompacted_runs=history_runs(settings),
        compacted_token_budget=compaction_budget(settings),
        store_compacted_messages=True,
        search_compacted_messages=True,
        on_context_overflow=True,
        enforce_min_fold_ratio=True,
    )
    tools = tools_for_mode(mode, settings)
    names = tool_names(tools)
    # 提示词只描述真正装配进来的能力：read-only 下不提写文件与 shell。
    hints = SHELL_HINT if "run_shell_command" in names else ""
    hints += POWERSHELL_HINT if "run_powershell" in names else ""

    model_instance = catalog.build(provider, model_id)
    db = SqliteDb(db_file=str(DB_FILE))

    memory = None
    if settings.get("memory.enabled"):
        # model 与 db 必须显式给出：Agno 只在 memory_manager 为 None 时才用 agent 的
        # model/db 补齐，已传入而不补会得到 db=None（记忆静默不落库）。
        memory = MemoryManager(
            model=model_instance,
            db=db,
            delete_memories=bool(settings.get("memory.delete_memories")),
            clear_memories=bool(settings.get("memory.clear_memories")),
        )

    return Agent(
        model=model_instance,
        fallback_models=fallback_models or None,
        compaction=compaction,
        # 超过 16k 字符的工具结果落 AgentFS，上下文只留信封与回读方式。
        offload_tool_results=True,
        tools=tools,
        memory_manager=memory,
        enable_agentic_memory=memory is not None,
        add_memories_to_context=True if memory is not None else None,
        # 会话持久化到 ~/.aaa/data/sessions.db；记忆条目也落在同一个库。
        db=db,
        # Agno 把 session metadata 写进会话记录；`-c` 据此只续接当前目录的会话。
        metadata={"cwd": str(Path.cwd())},
        # 系统提示词只描述身份与工具用法，不承担任何权限约束。
        instructions=(
            "你是运行在用户终端里的助手。"
            f"当前可用工具：{'、'.join(names)}。"
            f"当前权限模式：{mode}。"
            "工具返回错误时如实说明，不要编造结果。"
            + hints
        ),
        # 把同一 session 的历史消息带进下一轮；轮数上限只是防止无限增长。
        add_history_to_context=True,
        num_history_runs=history_runs(settings),
        markdown=False,
    )
