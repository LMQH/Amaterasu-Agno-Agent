# memory — 记忆

## 边界与目标

记忆默认使用 Agno 原生实现：条目是 `UserMemory`（落在 `~/.aaa/data/sessions.db`），模型经 `update_user_memory` 工具主动增删，条目在每轮进入 **system prompt**。本模块负责装配选择与配置键，不重新实现存储或检索。

切换点是构造期的引擎选择（配置 `memory.enabled` 与未来的引擎键），不碰 Agno 执行路径。

## 拥有者与不变量

- **归属维度**：`user_id`，取自配置 `memory.user_id`；一个用户一个池，不按目录分。
- **产生方式**：`enable_agentic_memory`。模型自己决定记什么；不启用每轮后台抽取（`update_memory_on_run` 与前者互斥）。
- **删除权限**：`delete_memories` 与 `clear_memories` 都开放给模型。
- **条目语义**：完全遵循 Agno——`memory` 文本、`memory_id`、`topics`、`user_id`、`input`、`created_at/updated_at`。没有版本号、没有留史：写入 last-write-wins，删除是真删。
- **装配约束**：`MemoryManager` 必须显式传入与 Agent 相同的 `model` 与 `db`。Agno 只在 `memory_manager is None` 时才用 Agent 的 model/db 补齐；已传入而不补会得到 `db=None`，记忆静默不落库（已实测）。
- 关闭记忆（`memory.enabled = false`）时 `memory_manager` 为 `None`，且不传 `enable_agentic_memory` / `add_memories_to_context`，Agno 不初始化记忆。

## 对外接口

- 配置键：`memory.enabled`、`memory.user_id`、`memory.delete_memories`、`memory.clear_memories`。
- 装配点：`runtime.build_agent`；`user_id` 由 `cli/app` 传给 `stream_run`，再传给 `agent.run` / `continue_run`。
- 已知例外（登记在 `boundary`）：`update_user_memory` 由 Agno 内部注册，不在 `build_tools` 返回的工具集里，因此不受权限模式约束，也不出现在提示词的工具清单中。

## 已接受的风险

1. **注入无预算**。Agno 注入路径全量读取该 `user_id` 的所有条目，没有条数或 token 上限；记忆增长会线性挤占 system prompt 并让缓存前缀失效。缓解只能靠定期清理或 `MemoryOptimizationStrategy`。
2. **不可恢复**。`clear_memories` 开放后，模型一次误判就能清空全部记忆；无版本、无留史。
3. **system prompt 变化**。记忆条目参与 system prompt，每轮前缀可能不同；这是选择 Agno 原生语义的直接后果。

## 已否决做法

- 自研引擎（`propose/get/search/forget` + `expected_revision` + 双预算）：与 Agno 原生能力重复，且注入位置、版本语义都要自己维护 → 改用 Agno 原生，接受其 last-write-wins 语义。
- 把注入落 `additional_input`（第 5 类）：一旦使用 `add_memories_to_context`，Agno 固定写在 system prompt → 接受。
- 每轮后台抽取（`update_memory_on_run`）：与 agentic 模式互斥，且单轮 `-p` 进程退出可能丢掉本轮记忆 → 不启用。

## 待定

- 外置记忆引擎（外部注入服务或额外工具）的接入形态，随「插件」设计一起定。届时需明确：由谁负责注入（system prompt 还是 `additional_input`）、是否提供自有工具、是否需要独立模型与存储。
