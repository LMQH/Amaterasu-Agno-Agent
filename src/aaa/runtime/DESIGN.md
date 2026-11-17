# runtime — 模块设计

## 边界与目标

Agent 装配与进程日志。把 Provider、Tools、Context、Boundary、Memory 与 sqlite 持久化拼成一个可用 Agent；不介入 Agno 执行路径，只在装配点传参。

## 拥有者与不变量

- `build_agent` 是 Agent 的唯一构造点，其他模块只消费实例。
- 切换模型或权限模式一律重建 Agent，不原地改 `agent.model` / `fallback_models` / `fallback_config`。
- 持久化固定为 `~/.aaa/data/sessions.db`（`SqliteDb`）；`metadata={"cwd": …}` 写进会话记录，是 `-c` 的目录归属依据。
- 压缩参数全部来自 `context`（其值来自 `config.toml`）：阈值 `compact_threshold(window, settings)`、`uncompacted_runs=history_runs(settings)`、预算 `compaction_budget(settings)`，并开启压缩消息存储/搜索与溢出即压缩。
- 工具装配有唯一入口 `tools_for_mode(mode, settings)`：`boundary` 给能力集合、根与确认名单，`tools.assemble` 做装配，数值上限从配置传入。
- 系统提示词由实际工具名与 `mode` 生成，只描述身份与工具用法，不承担权限约束。
- 记忆由 `memory.enabled` 决定：开启时构造 `MemoryManager(model=同一个 model 实例, db=同一个 SqliteDb)` 并传 `enable_agentic_memory=True`、`add_memories_to_context=True`；关闭时三者都不传。model 与 db 必须显式给，Agno 只在 `memory_manager is None` 时自动补齐。
- 不启用 knowledge 与治理策略；`add_history_to_context` 与 `num_history_runs` 负责把同会话历史带进下一轮。
- `fallback_models` 为空时传 `None`，不传空列表。

## 对外接口

- `build_agent(catalog, provider, model_id, mode, settings) -> Agent`：`catalog.require` 的 `ValueError` 直接上抛，由调用方（启动参数解析、`/model`）转成提示。
- `tools_for_mode(mode, settings) -> list`。
- `setup_logging(settings)`：给 `agno` 与 `aaa` 两个 logger 挂同一个文件 handler，重复调用不重复挂载；级别取 `log.level`，`AAA_LOG_LEVEL` 可临时覆盖。
- 日志轮转与库告警阈值来自 `log.max_bytes` / `log.db_warn_bytes`；`sessions.db` 超限只告警，不清理。

## 已否决做法

- 原地改 `agent.model` 换模型：Agno 只在构造时把 `fallback_models` 转成 `fallback_config`，原地改两个字段必然漏一个，fallback 会指向旧渠道 → 统一重建。
- 替换或重定向 Agno 的 logging 配置：会改变它的行为 → 只给它的 logger 附加 file handler。
- 自动清理过期会话或大库：用户数据，程序无权自动删除 → 只提示手动归档。
