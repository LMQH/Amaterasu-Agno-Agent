# 总架构 — aaa Harness

定位：运行在终端里的 agent harness，底层是 Agno 3.1.12。本文只写系统结构与不可违反的约束；工作方式见 `AGENTS.md`，用法见 `README.md` 与 `docs/cli.md`，单个模块的边界见各模块 `DESIGN.md`。

## 一、五层职责与 Agno 的边界

| 层 | 由谁实现 | 本项目的落点 |
|---|---|---|
| Provider | Agno `models/` | 只提供渠道与模型元数据（`context_window`、`api` 协议名）；`model` 模块构造实例 |
| Tools | Agno + 本项目工具 | `tools` 模块实现工具本体；`boundary` 决定哪些工具可见 |
| AgentLoop | Agno `Agent` | 不介入；只在装配点传入参数 |
| Context | Agno compaction / offload | `context` 持有压缩与历史轮数的参数；`memory` 提供记忆引擎 |
| Boundary | Agno HITL / hooks | `boundary` 声明确认规则（哪些工具需确认、审批策略、危险命令规则、什么算同一次批准）；`cli` 执行询问、签名记忆与非交互拒绝 |
| Usage | 本项目账本 | `usage` 只读 Agno 的 metrics，把 `(渠道, 模型)` 的 token 与金额写进独立 `usage.db`；不介入任何执行点 |

Agno 拥有全部**执行点**：消息拼装、工具循环、压缩触发、会话写入。本项目只在**装配点**（构造参数、工具、run 级钩子、事件）与**数据**（数据库、文件系统）上扩展。

## 二、模块划分

```text
src/aaa/
├── config/      # secret.yaml（渠道/密钥）+ config.toml（可调设置）：IO、归一、探查
├── model/       # 模型身份与构造：provider 值对象 + catalog 解析
├── runtime/     # Agent 装配与进程日志
├── context/     # 上下文参数（压缩阈值、保留尾轮数、摘要预算）
├── boundary/    # 权限策略：模式→能力清单、确认规则、文件根（不装配工具）
├── tools/       # 工具域与装配：builtin/（文件、检索、进程、待办）、extensions/（天气）
├── memory/      # 记忆设计：默认 Agno 原生引擎；后续引擎与接口在此设计并实现
├── usage/       # 用量与花费：读 Agno metrics，写独立账本 usage.db
├── sessions/    # 会话查询、命名、标题、目录→会话索引
└── cli/         # 入口、参数、命令、状态、渲染、事件消费
```

依赖方向单向，下层不 import 上层：

```text
cli     → runtime, model, boundary, config, context, sessions, usage
runtime → model, boundary, config, context, tools
sessions→ model, config
usage   → config, model
config  → model, boundary
model / context / boundary / tools / memory → 本包内无依赖
```

`boundary` 与 `tools` 互不 import：前者只声明「模式允许哪些能力 + `Isolation(file_root, command_cwd)`」，后者只按「能力名清单」装配；两者由 `runtime.tools_for_mode` 合并。`resolve_policy` 的签名即 `PolicySource`，可整体替换（沙箱/插件），工具与运行时都不用改。`memory` 当前只有设计说明：默认引擎是 Agno 原生 `MemoryManager`，装配在 `runtime`；后续替换引擎在 `memory/` 内实现，替换只发生在构造期。`usage` 只读 Agno 的 db 与 metrics、只写自己的 `usage.db`，不依赖执行路径；它拿到的只有 `config.paths` 与 `model.provider` 的值对象，不认识 `Catalog`（取价函数由 `cli` 注入）。

## 三、铁律

1. **不改 Agno 的执行路径。** 不覆写 `Model.response`/`response_stream`，不修改 `Agent` 内部实现，不自建循环。需要执行点之外的能力时，先判定它是否可以用装配点表达。
2. **成本治理不进入运行路径。** 用量事后归因：`usage` 只读 Agno 的 metrics（run 级、按模型角色），把金额写进自己的 `usage.db`；金额在入账时冻结，改价不改历史。在线预算、阶梯降级、条目流一律不做。
3. **记忆默认用 Agno 原生。** 条目是 `UserMemory`，经 `MemoryManager` 落 `sessions.db`；替换点只在构造期（配置选择引擎），不碰执行路径。
4. **记忆注入随引擎。** 默认引擎把条目写进 system prompt（Agno 原生语义，按 `user_id` 归属）；换引擎若要落消息侧 `additional_input`，差异必须写进该引擎的设计说明。
5. **模型身份是 `(provider, model_id)`。** 切换模型一律重建 `Agent`，不原地改 `agent.model` / `fallback_models` / `fallback_config`。
6. **唯一构造点。** 模型由 `model.catalog.build` 构造（唯一对外入口，内部转 `model.provider.build_model`），`Agent` 由 `runtime.agent.build_agent` 构造；其他模块只消费实例。
7. **单向依赖。** `cli` 不被任何下层 import；记忆没有独立代码，装配在 `runtime`；`usage` 只读 Agno 的 db 与 metrics、只写自己的账本。
8. **一个事实一个维护位置。** 文档不复制代码，模块文档不复述总架构；每项信息只有一处权威，其余只作导航。
9. **隔离强度分级，不承诺 OS 级隔离。** 文件工具受工作区根约束、`grep` 受根目录约束、`shell` 只有工作目录与人工审批；沙箱（容器/OS 机制）不在本期承诺。对外表述必须按这个强度说，不得把路径检查说成隔离。

## 四、设计思想综概

- **薄契约前置，代码驱动**：模块的实现方式由可运行闭环决定，边界与不变量写进 `DESIGN.md`，不预演内部结构。
- **谁拥有状态谁成模块**：配置文件、模型身份、权限模式、目录→会话索引、记忆条目、用量单价各有唯一拥有者。
- **按 Agno 的接缝划界**：能在装配点表达的留在装配层；必须碰执行点的能力，宁可不做，也不把治理渗进 Provider。
- **模块解耦、边界分明**：谁也不替别人做决定——策略不装配、装配不读配置、工具不认权限模式；需要合并的地方只留一个显式节点（如 `runtime.tools_for_mode`）。
- **可替换优先于可配置**：引擎、渠道、模型都在构造期选定；“可替换”指换实现，“可配置”只是选择实现的入口，运行期不切换，不为假设场景预留热切换开关。
- **可调数值一律配置化**：默认值集中在 `config/settings.py` 的键表，用户只经 `/config` 修改，程序写回 `config.toml`。

## 五、文档机制：一体双用

设计文档与代码是同一件事的两个面，必须同向：

- **代码领先时，文档跟上解释**：`DESIGN.md` 记录当前实现的作用、约束与不变量；与代码不一致即缺陷，先改文档。
- **文档领先时，文档就是计划**：新能力先在 `DESIGN.md` 的清单、可见性表或接口节里落一行，再动代码；此时该条目是计划与备忘，不是已实现事实。
- **判断谁领先**：看代码里有没有对应实现。有则写“是什么”，没有则写“打算是什么”，不混用。
- **项目级关键决策进总架构**：只有影响模块边界、依赖方向、Agno 接缝、隔离或安全策略的**跨模块**决定，以及设计哲学的取舍，写进本文对应章节；单个模块的内部取舍写在模块 `DESIGN.md`，不上升为总架构条目。
- **两条写入通道**：**由现有代码总结出来的解释**（结构、契约、现状）核对属实后直接写，不需要审批；**文档领先代码的设计与决策**（新能力、新接口、新原则）必须先经 owner 批准才能落盘，未批准前只作为讨论，不进文档。判断依据同上：代码里有没有对应实现。

`HANDOFF` 只放工作线状态（做到哪、卡在哪、下一步），不留设计。调研材料只是参考，不构成实现基线；其结论必须先转述进设计文档或代码才生效，设计文档不引用调研材料的链接或路径。

## 六、运行期契约

**配置分层**

| 文件 | 内容 | 写入方 | 权限 |
|---|---|---|---|
| `~/.aaa/secret.yaml` | 渠道、密钥、默认模型、可切换范围、模型价目（`cost`，可选） | 程序（`/provide` 向导），原子写入 | 0600 |
| `~/.aaa/config.toml` | 其余全部可调项（`context` / `tools` / `memory` / `model` / `boundary` / `log` / `sessions` / `ui` 八组） | 只经 `/config`，程序校验后全量写回 | 用户不手改 |

越界、类型错误与未知键：回落默认值并在 `Settings.warnings` 里记录，由 `cli` 提示，不静默采用。

**错误与退出码**

| 码 | 含义 |
|---|---|
| 0 | 成功 |
| 1 | 运行失败（模型/工具/未捕获异常） |
| 2 | 用法或配置问题（含损坏的 `secret.yaml`：报错退出且不覆盖原文件） |
| 130 | 被 Ctrl-C 取消 |

工具失败一律变成 `Error: …` 文本回填给模型，不抛穿进程；非交互模式下需确认的工具默认拒绝并写日志，`--allow-shell` 显式放行 `run_shell_command`。审批策略 `boundary.command_approval` 决定「需要确认的工具」这一次是否真的问人（`always` / `dangerous`），它只影响询问，不改变工具可见性。

**数据位置与生命周期**

| 路径 | 内容 | 生命周期 |
|---|---|---|
| `~/.aaa/data/sessions.db` | 会话、消息、`session_state`、记忆条目，以及索引表 `aaa_cwd_session`（目录 → 最近会话） | 超过 `log.db_warn_bytes` 只告警，不自动清理 |
| `~/.aaa/data/usage.db` | 用量账本：终态 run × 模型角色的 token 与冻结金额 | 派生数据，可删除重建 |
| `~/.aaa/logs/aaa.log` | 运行日志 | 超过 `log.max_bytes` 轮转，保留 `.1`、`.2` |
| `~/.aaa/history` | 输入历史 | 由 prompt-toolkit 维护 |

**验证入口**

```bash
./tests/run.sh                       # 模块回归，零网络
./tests/run.sh e2e [--pty]           # 真实渠道闭环（P0 + P1，`--pty` 追加交互面）
```

验证记录按六项写进 `HANDOFF` 验证段：日期、环境、命令、预期依据、结果、证据位置。`tests/README.md` 维护用例清单与“已知测不了”。

## 七、依赖与可复现性

- **唯一事实源**：`pyproject.toml` 声明直接依赖（五个，全部 `==` 精确钉），`uv.lock` 锁定完整解析（48 条记录，含 Windows / emscripten 的 marker 项）。仓库不提供 `requirements.txt`，也不靠 import 名单反推依赖。
- **安装只有一条路**：`uv sync --frozen`。不在项目环境里 `pip install` 补包——那会让实际环境偏离锁，`--frozen` 下一次就会失败或抖动。
- **Python 边界**：`requires-python = ">=3.11,<3.14"`。下限由 `import tomllib` 决定；上限的含义是「未验证的版本不允许被自动选中」，实测基线为 3.13.12。
- **锁即基线**：`[tool.uv] constraint-dependencies` 把 5 个容易浮动的传递依赖回钉到实测版本。改动它们等于换基线，必须重跑真实渠道 e2e，不能只看单测。
- **升级是显式动作**，不随 `uv sync` 自动发生：改 pin 就要重跑 `uv lock` 与真实渠道 e2e。升级步骤与「何时开启新版本隔离期（`exclude-newer`）」只有一份，维护在 `docs/memo.md`。
- **锁与代码同批交付**：新增或改版本必须同时提交 `uv.lock`；锁文件不跟随代码变化，就等于基线失真。
- **可复现的边界**：锁保证「解析结果与已验证环境逐包一致」，不保证跨平台行为已验证——Windows 的 PowerShell 与后台任务分支仍未实跑（见 `tests/README.md` 的已知测不了）。

## 八、待定

- 记忆多引擎：默认 Agno 原生；其他引擎的实现与巩固面在 `memory/` 内设计，接口需同时支持“不实现巩固”的引擎。
- 沙箱（OS 级隔离）：本期不做；接入点是 `boundary.Isolation` 的声明与可替换的 `PolicySource`。
- **数据保留策略**：会话库只增不减；清理方式（TTL、按大小、手动命令）未定。后台任务状态在进程内，不涉及磁盘保留。
- **错误模型统一**：工具用 `Error:` 文本、配置用 `ConfigError` 异常、其余走退出码；是否需要一份错误分类约定未定。
- **配置键增改流程**：新增可调项是否必须先在 `config/DESIGN.md` 记录并评审，未定。
