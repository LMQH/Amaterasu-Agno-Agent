# boundary — 模块设计

## 边界与目标

权限与边界声明。把「模型能做什么」表达成能力名集合，把「隔离到哪」表达成 `Isolation(file_root, command_cwd)`，再交给 `runtime.tools_for_mode` 合并、`tools.assemble` 装配。审批的**规则**在本模块（哪些工具需确认、什么算同一次批准），审批的**交互**在 `cli`。本模块不装配工具、不读配置、不认识具体实现。

## 拥有者与不变量

- 模式是封闭三档：`read-only`（默认）、`workspace-write`、`danger-full-access`；`MODES` 是唯一来源，`cli/args` 的 `--permission` 与 `/mode` 都从它取值。
- 能力名（`read` / `list` / `grep` / `write` / `edit` / `move` / `delete` / `shell` / `powershell`）的词汇与实现归 `tools`；本模块只做「模式 → 能力」授权。
- `read-only`：`read`/`list`/`grep`，没有写与命令。
- `workspace-write`：再加 `write`/`edit`/`move`/`shell`；shell 每次执行需确认。
- `danger-full-access`：再加 `delete`/`powershell`；shell 不需确认，文件根为 `/`。
- 文件根：前两档是 cwd，`danger-full-access` 是 `/`。
- 默认模式来自配置 `boundary.default_mode`（`restart` 生效）；模块内不保留默认模式常量。
- 提示词描述的能力由 `tool_names()` 从实际装配结果展开，不手写工具清单。

## 对外接口

- `resolve_policy(mode, base=None) -> ModePolicy`：完整声明（能力、确认名单、隔离范围），是默认实现。
- `PolicySource = Callable[[str, Path], ModePolicy]`：替换点；沙箱或插件给出自己的实现，工具与运行时都不用改。
- `Isolation(file_root, command_cwd)`：只描述隔离范围，不描述执行方式。
- `capabilities(mode)`、`confirm_tools(mode)`、`root(mode)`、`isolation(mode)`：薄访问器。
- `signature(tool_name, args) -> str`：审批签名键（工具名 + 键序无关的参数），决定「什么算同一次批准」。
- `MODES`：模式名单的唯一来源，`config.settings` 的 `boundary.default_mode` 可选项也取自它。
- 调用方是 `runtime.tools_for_mode`：它把能力集合、根、确认工具名与数值上限交给 `tools.assemble.build_tools`。

## 已知例外

开启记忆时，Agno 内部追加 `update_user_memory` 工具，它不经过能力清单，因此不受权限模式约束，也不出现在提示词的工具清单里。「工具集是唯一防线」对它不成立，这是接受 Agno 原生记忆的代价。

## 已否决做法

- 用系统提示词声明权限（「不要删除文件」）：只是建议，且与工具集可能分叉 → 能力集合是唯一防线，提示词只陈述事实。
- 在 boundary 内按模式写工具装配分支：每加一种能力都要改两处 → 改为 capability 集合 + `tools.assemble` 单点装配。
- 在 boundary 内自建审批实现：Agno 已有 HITL 暂停/继续协议 → 只用 `requires_confirmation_tools` 标注，审批在 `cli/run` 消费。
