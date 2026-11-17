# HANDOFF

- 更新日期：2026-11-18
- 版本控制：git（`origin` → `https://github.com/LMQH/Amaterasu-Agno-Agent.git`），按模块批次提交；依赖由 `pyproject.toml` + `uv.lock` 复现。
- 当前状态：`src/aaa/` 可运行，37 个 `.py`（3051 行）。配置拆成 `secret.yaml`（渠道与密钥）与 `config.toml`（其余全部可调项，经 `/config` 修改）；记忆默认开启，使用 Agno 原生 `MemoryManager`；工具按能力名装配（`builtin/` + `extensions/` + `assemble.py`）。依赖由 `pyproject.toml`（五个直接依赖，精确钉）+ `uv.lock`（48 条记录）管理，`uv sync --frozen` 建环境；Python `>=3.11,<3.14`。

## 代码结构

- `config/paths` — `~/.aaa/` 下的全部路径常量。
- `config/settings` — `config.toml` 的键表（`KEYS`）、读写、校验、`to_toml` 序列化；新增可调项只改这张表。
- `config/loader` — `secret.yaml` 的 v2 schema、v1→v2 归一、`ConfigError`、`probe_models`。
- `model/provider` — `Channel` / `ChannelModel` 值对象、`API_CLASSES`、`build_model` / `build_title_model`（超时与重试来自 settings）。
- `model/catalog` — `Catalog` 构造时绑定 settings：`require` / `scope` / `resolve` / `window` / `build` / `fallbacks`。
- `runtime/agent` — `build_agent(catalog, provider, model_id, mode, settings)` + `tools_for_mode` + 记忆装配。
- `runtime/logging_setup` — 日志落盘、轮转、库大小告警（阈值与级别来自 settings）。
- `context/params` — `history_runs` / `compaction_budget` / `compact_threshold(window, settings)`。
- `boundary/policy` — `MODES` 与「模式 → 能力集合 / 确认名单 / 文件根」，不装配工具。
- `tools/assemble` — 按能力名清单装配；`builtin/{files,processes,powershell,todos}`、`extensions/weather`。
- `sessions/query` — 会话查询、`new_session_id(settings)`、标题生成；目录→会话索引在 `sessions/index`（库表 `aaa_cwd_session`）。
- `cli/{args,app,state,run,ui,completer,commands}` — 入口、状态、渲染、事件与斜杠命令（含 `/config`）。

依赖单向：`cli → runtime/model/boundary/config/context/sessions`、`runtime → model/boundary/config/context/tools`、`sessions → model/config`、`config → model`；`model`/`context`/`boundary`/`tools`/`memory`/`usage` 无包内依赖。`boundary` 与 `tools` 互不 import，由 `runtime.tools_for_mode` 合并。

## 关键约定

- **配置两分**：`secret.yaml` 只放渠道、密钥与默认模型；`config.toml` 放其余全部可调项。用户不手改 `config.toml`，只经 `/config`（无参菜单 / `键 值` 行内），程序校验后全量写回。
- **生效方式**：`runtime` 当场重建 Agent；`immediate` 下次使用生效；`restart` 下次启动生效（日志、库阈值、默认权限模式）。非法值拒绝并保持原值；文件中的非法值回落默认并打印警告。
- **记忆**：默认开启（`memory.enabled`），`enable_agentic_memory` 模式，条目落 `sessions.db`，`user_id` 取 `memory.user_id`（一个用户一个池），`delete_memories` / `clear_memories` 均开放。`MemoryManager` 必须显式传 `model` 与 `db`，否则 `db=None`、记忆静默不落库。
- **记忆注入**：随 Agno，写进 system prompt 的 `<memories_from_previous_interactions>`；无条数/token 预算。
- **用量账本**：`/usage` 从 `usage.db` 读账本；账本由 `usage.ledger.sync` 从 `agno_runs` 的终态 run 增量生成，`(渠道, 模型)` 计价、金额入账时冻结、未定价只补空不改写。渠道键由 `stream_run(metadata={"channel": …})` 记入 run；没有该字段的历史 run 永久未定价。价目表在 `secret.yaml` 的 `models[].cost`（美元/百万 token，可选峰谷窗口）。
- **后台任务**：`run_shell_command(background=true)` 的 job 状态只在进程内（`ProcessTools._jobs` + 读线程有界缓冲，1MB / 20 条），进程退出时 `atexit` 杀掉未结束的进程组；不落盘，跨 `-p` 调用查不到上一次的 job。
- **工具**：`boundary` 只授权能力名（`read`/`list`/`grep`/`write`/`edit`/`move`/`delete`/`shell`/`powershell`），`tools.assemble` 装配，数值上限由 `runtime.tools_for_mode` 从配置传入。
- **已知例外**：`update_user_memory` 由 Agno 内部注册，不受权限模式约束，也不在提示词工具清单里。
- **模型/Agent**：模型身份是 `(provider, model_id)`；换模型、模式或运行相关配置一律重建 Agent，不原地改。
- **边界**：`boundary` 只声明「允许什么 + 隔离到哪」——能力清单、确认名单、`Isolation(file_root, command_cwd)`；不装配工具、不读配置。装配在 `tools.assemble`，参数在 `config.settings`。
- **隔离可替换**：`boundary.resolve_policy(mode, base)` 是纯函数，签名即 `PolicySource`；`runtime.tools_for_mode(mode, settings, policy=...)` 接受替换实现（沙箱/插件），工具与运行时都不用改。
- **审批两分**：`boundary` 出规则（`confirm_tools(mode)` 决定哪些工具问、`signature(tool, args)` 决定什么算同一次批准、`needs_approval(tool, args, strategy)` 决定这一次要不要问）；`cli` 出交互（询问、签名记忆、非交互拒绝）。
- **审批策略**：`boundary.command_approval` —— `always`（默认，每条命令都问）或 `dangerous`（只问命中 `boundary/danger.py` 规则的命令，其余自动放行并记日志）。只影响 `workspace-write` 下的 shell/PowerShell；`danger-full-access` 无审批、`read-only` 无命令工具。改键立即生效，不重建 Agent。
- **非交互**：默认拒绝需确认的工具；`--allow-shell` 只放行 `run_shell_command`（json 输出 `confirm_approved`）。

## 待定 / 阻塞

- **沙箱（备忘，暂不讨论）**：Agno `sandbox/` 只挂 `ClaudeAgent`/`CodexAgent`，生命周期归 AgentOS，本项目的 Agent 用不上；真要做需自建进程级隔离（容器或 OS 机制）并作为独立模块。接入点已留好：`boundary.Isolation` 声明范围，`PolicySource` 可替换，沙箱模块消费同一份声明。
- 当前隔离强度：文件工具受 `Workspace(root, allowed)` 约束、grep 受 `CodingTools(restrict_to_base_dir)` 约束；**shell 只有 cwd 与审批，无路径约束**——这是已知缺口。

- 外置记忆引擎（外部注入服务或额外工具）的接入形态随「插件」设计一起定；届时需明确注入位置差异。
- `README.md` 的项目定位仍是占位，等 owner 给业务范围。
- 真实渠道已通（tokenhub + deepseek 官方）；已由 `tests/e2e.py` 覆盖，未覆盖项见 `tests/README.md`。
- `-p` 单轮不生成会话标题；记忆写入只在模型主动调用 `update_user_memory` 时发生。

## 下一步

1. 真实渠道已跑通工具闭环与压缩/卸载；记忆写入 → 下一轮注入仍未真实验证。
2. `tests/` 已建：`test_units.py`（设置/解析/模式→能力/审批/后台任务/PowerShell/策略替换点/会话索引）与 `e2e.py`（真实渠道闭环）。
3. **已定、待实现**：CLI 新增 `/clear`（清空上下文、保留会话 id），先落在 `cli/DESIGN.md` 需求区；CLI 面整体待定版。
4. 用量账本已落地；未覆盖：真实渠道下 `cached_tokens` 是否被上报（本机尚未观测到缓存命中，`cache_read` 列可能长期为 0）。

## 定版状态

- 代码进入**定版讨论阶段**：功能闭环已闭合，离线回归 `./tests/run.sh` 为 34 tests OK。
- 定版前提（全部满足才转入打包发布讨论）：
  1. 真实渠道 e2e 全绿（`./tests/run.sh e2e`，交互面另加 `--pty`）；
  2. 记忆写入 → 下一轮注入有真实证据（当前只有单测）；
  3. 已知缺口逐条明确「接受」而非「未知」：shell 无路径约束、后台 job 不跨 `-p` 进程、渠道字段上线前的旧 run 永久未定价、Windows 分支未实跑；
  4. 依赖基线未变动（`uv sync --frozen` 与 `uv.lock` 逐包一致）。
- 打包与发布形态（`docs/research/python-release-playbook.md`）留到定版之后单独讨论，本轮不展开。

## 验证

- 日期 2026-11-18，macOS arm64，解释器 `./.venv/bin/python`（agno 3.1.12），用量账本落地：
  - 新增 `usage/cost.py`（四类 token × 单价 × 峰谷乘数，本地时间窗口可跨午夜）、`usage/ledger.py`（`usage.db` 建表、终态 run 增量同步、run 更新重放、未定价补算）、`usage/report.py`（自然日/周/月聚合，按输入+输出降序）。`secret.yaml` 的 `models[].cost` 由 `model.provider.parse_cost` 校验，非法价目丢弃并告警；`ChannelModel.cost` 由 `Catalog.cost(渠道, 模型)` 取。`stream_run` 新增 `channel` 参数，写进 `agent.run(metadata=…)`。`/usage`（day/week/month）在 `cli` 渲染。
  - 预期依据：金额 = 四类 token × 单价 / 1e6 × 峰谷乘数；同一 run 不重复入账；暂停中的 run 不入账；未定价只在配出价后补一次；报表按 `(渠道, 模型)` 聚合、token 降序、未使用不出现。
  - 结果：`./tests/run.sh` → **34 tests OK**（新增 9 条：计价与跨午夜窗口、非法价目拒绝、同步幂等与更新重放、暂停 run 不入账、未定价补算一次、渠道未知永久未定价、报表排序与周期边界、CJK 对齐、零缓存列隐藏）。
  - 真实写入路径：`stream_run(channel="tokenhub")` 后 `agno_runs.run_data['metadata']` 为 `{"channel": "tokenhub"}`，同库 `status=COMPLETED`。
  - 真实读取路径：临时 `HOME` 下用 Agno 原始形状的 `run_data` 造 3 条终态 + 1 条 PAUSED → `sync` 报 `added=3`；`deepseek` 行金额 `$0.09468` 与手算一致；`tokenhub` 行 `$0.0218`；无渠道行金额为 `?` 且表尾计数 1 条；PAUSED 行未入账。

- 日期 2026-11-17，macOS arm64，解释器 `./.venv/bin/python`（agno 3.1.12），后台任务改为进程内状态：
  - `ProcessTools` 去掉 `jobs_dir`：job 记在 `_jobs` 字典，输出由读线程读进有界缓冲（默认 1MB，超出丢最旧字节），状态由 `Popen.poll()` 判定；已结束 job 保留 20 条；`atexit` 杀未结束的进程组并关闭管道。`build_tools` / `tools_for_mode` 同步去掉 jobs 目录参数，磁盘 `~/.aaa/data/jobs/` 不再创建（本机原本就不存在该目录）。
  - 预期依据：后台 job 的输出与退出码可轮询、可终止；不产生任何磁盘文件；父进程退出后不留下孤儿进程。
  - 结果：`./tests/run.sh` → **25 tests OK**（新增「状态不落盘」一条：起后台 job 后工作目录仍为空）；`tests/e2e.py --list` → 12 条正常；`python -m aaa --help` 退出码 0。
  - 真实进程验证：子进程里起 `sleep 60` 的 background job，父进程退出后 `kill -0 <pid>` → 进程已不存在（`atexit` 生效），仓库内无 `jobs/` 目录。

- 日期 2026-11-17，macOS arm64，解释器 `./.venv/bin/python`（agno 3.1.12），新增 `boundary.command_approval`：
  - 新增 `boundary/danger.py`（18 条规则，按「类别 → 正则 → 理由」声明）、`policy.needs_approval(tool, args, strategy)`、`config` 键（默认 `always`，`/config` 可改，`immediate` 生效）；`cli.run.approve_requirements` 与 `stream_run(strategy=)` 接入，`cli.app` 两处调用点传配置值。
  - 预期依据：`always` 保持旧行为；`dangerous` 下未命中规则的命令不再询问且真的执行，命中规则仍询问；`danger-full-access` 完全不受影响。
  - 结果：`./tests/run.sh` → **24 tests OK**（新增 5 条：策略自动放行、危险命令仍询问、`needs_approval`/`danger_reason` 边界与未知策略报错、`Settings` 默认值与非法值、`stream_run` 策略透传并断言询问次数）；`tests/e2e.py --list` → 12 条用例正常；`python -m aaa --help` 退出码 0。
  - 真实工具路径（`FakeModel` 驱动，无网络）：`dangerous` + `touch <marker>` → 未询问且文件真的被创建；`dangerous` + `rm -rf …` → 进入询问；`always` + `echo hello-aaa` → 询问 1 次。配置读写：`save` 后 `config.toml` 含 `[boundary] command_approval = "dangerous"`，`load_settings` 回读一致、无警告。
- 日期 2026-11-17，macOS arm64，解释器 `./.venv/bin/python`（agno 3.1.12）：测试体系收敛为最小闭环——三份离线测试合并进 `tests/test_units.py`（19 条），删除两块冗余 e2e（P1.9 永远 SKIP、P1.10 与 P0.5 重复）。`./tests/run.sh` → **19 tests OK，0.4 秒**；`tests/e2e.py --list` → 12 条（P0 十条 + P1 两条 + PTY 一条）；`tests/e2e.py --suite p1` → **2 PASS / 0 SKIP，142 秒**（P1.7 第 5 轮触发折叠，P1.8 答对但未走检索工具）。未覆盖：`-c` 的端到端路径（见 `tests/README.md` 已知缺口）。

- 日期 2026-11-17，macOS arm64，解释器 `./.venv/bin/python`（agno 3.1.12）：补齐测试分层——新增 `tests/fixtures.py`（假模型）、`tests/test_agent_loop.py`（工具往返 / HITL 确认 / HITL 拒绝）、`tests/test_config_settings.py`、`tests/test_context_params.py`、`tests/run.sh`（固定 TZ/LC、清代理、`-W error::ResourceWarning`）。`./tests/run.sh` → **42 tests OK**，零网络。未覆盖：`-c` 的端到端路径（已记入 `tests/README.md` 的已知缺口）。

- 日期 2026-11-17，macOS arm64，解释器 `/tmp/aaa-verify/bin/python`（agno 3.1.12）：目录→会话的持久化由文件指针改为库内表 `aaa_cwd_session`。`unittest` → **29 tests OK**（新增索引表 3 条：未知目录、覆盖推进、`seq` 单调）。`tests/e2e.py --only P0.4` → **PASS**，但该用例走的是 `-r`（按 id 前缀），**不经过新索引**；`-c` 的端到端路径当前无用例，仅由单测覆盖。

- 日期 2026-11-17，macOS arm64，解释器 `/tmp/aaa-verify/bin/python`（agno 3.1.12 + tiktoken 0.14.0；原环境被系统清理，已用 uv 按同版本重建）：架构决策 0–5 落地。`unittest` → **26 tests OK**（新增 `signature` 键序无关与无参两条）；`tests/e2e.py --suite p0` → 9 PASS / 1 FAIL 后修正用例断言 → 复跑 P0.7 **PASS**（失败原因是 `config.loader` 的报错文案已改为「无法解析 …」，属测试滞后，行为未变）。

- 日期 2026-11-17，macOS arm64，uv 0.13.7 / CPython 3.13.12，环境 `./.venv`（`uv sync --frozen`；用于比对的临时环境随后已清理）：
  - 新增 `pyproject.toml` + `uv.lock`。直接依赖五个（`agno[openai,sqlite]==3.1.12`、`tiktoken==0.14.0`、`pyyaml==6.0.3`、`prompt_toolkit==3.0.53`、`questionary==2.1.1`）；`[tool.uv] constraint-dependencies` 把 `openai`/`pydantic-settings`/`sqlalchemy`/`httpcore2`/`httpx2` 钉回实测版本，否则纯解析会各升一个补丁/次版本。锁记录 48 条，其中 `colorama`（win32）与 `httpx2-jsfetch`（emscripten）为 marker 项，本机实装 45 个包。
  - 预期依据：锁定解析结果必须与被验证过的环境逐包一致。结果：新环境 45 个包与旧 `/tmp/aaa-verify` 版本集合完全相同（`only-new`/`only-baseline`/`version drift` 均为空）。
  - `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_*.py'` → **24 tests OK**；`python -m aaa --help` → 退出码 0；`tests/e2e.py --list` → 15 条用例全列，零请求。

- 日期 2026-11-17，macOS arm64，解释器 `/tmp/aaa-verify/bin/python`：删除死代码 `src/aaa/tools/shell.py`（全库无引用，唯一实例在 `builtin/processes.py`）。`unittest` → **24 tests OK**；`import aaa.runtime.agent, aaa.cli.app` → ok；`tests/e2e.py --only P0.8`（shell 执行路径）→ PASS。

- 日期 2026-11-17，macOS arm64，解释器 `/tmp/aaa-verify/bin/python`（agno 3.1.12），真实渠道：`boundary` 定为纯声明（能力 + 确认 + `Isolation`），工具装配归 `tools.assemble`，参数归 `config.settings`，`PolicySource` 作为隔离替换点。`python -m unittest discover -s tests -p 'test_*.py'` → **24 tests OK**（新增 5 条策略用例，含“替换 PolicySource 后工具面随之改变”）；`tests/e2e.py --only P0.1` → P0.1/P0.10 PASS；CLI `--help` 与全部模块 import 正常。

- 日期 2026-11-17，macOS arm64，解释器 `/tmp/aaa-verify/bin/python`（agno 3.1.12），`PYTHONPATH=src`，`HOME` 指向临时目录：
  - `python -m compileall -q src/aaa` → ok；22 个模块逐个 import → ok。
  - `Settings`：默认值（`memory.enabled=True`、`tools.shell_output_bytes=1_000_000`）、`set` 校验（越界/类型/枚举拒绝）、`save` 后 `config.toml` 含 `[tools]\nshell_timeout = 42`、重新 `load_settings` 回读一致。
  - 文件内非法值（`shell_timeout = "abc"`）与未知键：回落默认并产生两条警告，不抛异常。
  - `normalize_config` 用 `model.default_context_window=1234` 补窗口 → `Catalog.window == 1234`。
  - `tools_for_mode`：三档的能力集合、确认名单、文件根符合 `boundary.MODE_*`；`workspace-write` 装配出 `run_shell_command`、`job_output`、`job_kill`、`grep`。
  - `build_agent`：`memory_manager` 非空、`enable_agentic_memory=True`、`add_memories_to_context=True`；`add_user_memory` 后 `get_system_message` 含 `<memories_from_previous_interactions>` 与条目文本；`memory.enabled=false` 时不装记忆。
  - `/config tools.shell_timeout 45`：校验 → 写回 → 重建 agent（对象变化）；`/config log.level DEBUG`：写回但不重建，提示重启生效；未知键与越界值被拒绝且原值不变；菜单路径用打桩 questionary 走通（选组 → 选键 → 改值）。
  - `parse_args("read-only", ["-p","hi","--model","gw/m2"])` 与 `parse_args("workspace-write", [])` 的默认权限模式符合配置。
  - `stream_run` 把 `user_id` 与 `session_id` 透传给 `agent.run`（打桩 agent 捕获 kwargs）。
  - `python -m aaa --help` 退出码 0。
- 未覆盖：真实模型调用、真实 TTY 下的 `/config` 菜单与 `/provide` 向导、后台 job 轮询。
