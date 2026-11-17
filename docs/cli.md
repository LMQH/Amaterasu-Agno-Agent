# CLI 功能说明

当前终端界面的用法参考。渠道配置的字段与 v1→v2 迁移写在 `README.md`；本文只讲命令、模式与运行期行为。

## 启动

```bash
PYTHONPATH=src python -m aaa            # 交互 REPL
PYTHONPATH=src python -m aaa -p "..."   # 单轮，只输出正文
echo "..." | PYTHONPATH=src python -m aaa --mode json
```

- 首次启动（`~/.aaa/secret.yaml` 不存在或没有任何渠道）直接进入渠道配置向导；非交互模式下改为报错退出。
- 配置文件存在却读不出来（不是合法 YAML、顶层不是映射、写了渠道但没有一个可用）时报错退出，退出码 `2`，**不会进入向导、不会覆盖原文件**；只有「没有渠道」才算未配置。
- 已有配置则进入 REPL，打印 `输入 /help 查看命令，Ctrl-D 退出。`
- 依赖 agno 3.1.12 及其依赖项；缺依赖时导入即失败，先按 `README.md` 安装。

### 启动参数

| 参数 | 作用 |
|---|---|
| `message` | 位置参数，首条消息；非交互模式省略则从 stdin 读 |
| `-p`、`--print` | 单轮执行，只把助手正文写到 stdout 后退出 |
| `--mode interactive\|print\|json` | 输出形态；`json` 每行一个事件 |
| `-m`、`--model <引用>` | 本次运行使用的模型，支持 `渠道/模型` 与裸 id；歧义时报候选 |
| `--permission <模式>` | 本次运行的权限模式，取值同 `/mode` |
| `-c`、`--continue` | 续接当前目录最近使用的会话 |
| `-r`、`--resume <ID>` | 按会话 id 或前缀续接 |
| `--allow-shell` | 非交互模式下自动放行 `run_shell_command`（默认拒绝）；与 `--permission workspace-write` 搭配使用 |

- `--model` 只影响本次运行，不改写 `secret.yaml` 的默认模型。
- `-c` 与 `-r` 互斥。
- 退出码：`0` 成功，`1` 运行失败或被中断，`2` 用法/配置问题，`130` 被 Ctrl-C 取消。
- 非交互模式不生成会话标题，也不进入 REPL；`json` 模式最后一行是 `{"type":"result",...}`，含 `session_id`、`content`、`tokens`、`duration_s`、`error`。

### JSON 事件

`--mode json` 逐行输出，类型为 `model_start`、`content`、`tool_start`、`tool_done`、`tool_error`、`error`、`cancelled`、`confirm_required`、`confirm_approved`（带 `--allow-shell` 时），末行 `result`。每个事件带对应字段（`tool`、`args`、`duration_s`、`text`、`message`）。

## 数据位置

| 路径 | 内容 |
|---|---|
| `~/.aaa/secret.yaml` | 渠道、密钥、默认模型、可切换范围；权限 0600，原子写入 |
| `~/.aaa/config.toml` | 全部可调设置（记忆、压缩、模型超时、工具上限、默认权限模式、日志、界面、会话）；程序维护，`/config` 修改 |
| `~/.aaa/data/sessions.db` | 会话与消息、`session_state`、记忆条目，以及索引表 `aaa_cwd_session`（目录 → 最近会话，`-c` 据此续接）；超过告警阈值时日志提示，不自动清理 |
| `~/.aaa/data/usage.db` | 用量账本：每个终态 run × 模型角色的 token 与冻结金额；删掉可重建，历史金额随之重算 |

日志级别取 `config.toml` 的 `log.level`（默认 `INFO`），环境变量 `AAA_LOG_LEVEL` 可临时覆盖，排查时用 `DEBUG`。

`/config` 改完立即生效方式：运行相关项（记忆、压缩、模型、工具）当场重建 Agent；界面与会话条数下次使用生效；日志轮转与库告警阈值下次启动生效。

## 命令一览

| 命令 | 作用 |
|---|---|
| `/help` | 打印命令表 |
| `/provide` | 渠道编辑器：选渠道或新增，改协议、地址、Key、模型与窗口 |
| `/config` | 配置：无参进分组菜单；`/config <键>` 查看当前值与范围；`/config <键> <值>` 精确修改 |
| `/model` | 切换模型：列表选择、`<渠道>/<模型>` 精确切换、`next` / `prev` 循环 |
| `/mode` | 切换权限模式（`read-only` / `workspace-write` / `danger-full-access`） |
| `/compact` | 立即压缩当前会话上下文 |
| `/usage` | 用量与花费：默认今天，`/usage week` / `/usage month` |
| `/session` | 列出最近 20 个会话并切换；`/session <id>` 直接切换 |
| `/new` | 新建会话（旧会话仍可从 `/session` 找回） |
| `/exit` | 退出；空输入处 Ctrl-D 等价 |

非斜杠输入交给模型。运行中 Ctrl-C 取消本轮（向 Agno 发 `cancel_run`），REPL 不退出。

## `/provide`：渠道编辑

交互顺序固定：

1. 选择渠道（已有渠道列表 +「＋ 新增渠道」）。
2. 新增时输入渠道 id，只允许小写字母、数字、连字符；它同时是 `/model` 的前缀。
3. 选协议：`deepseek`（DeepSeek 原生，会发 `extra_body.thinking`）或 `openai-completions`（通用 OpenAI 兼容端点，不发私有参数）。
4. Base URL。
5. API Key：留空沿用已保存的 Key。
6. 用 `GET /models` 探查模型（有 15 秒超时）；探查失败或返回空时改手输，逗号分隔。
7. 勾选启用的模型。
8. 逐个确认上下文窗口（tokens）。
9. 默认模型：现有默认仍有效则保留，否则从全部渠道的模型里选。

行为边界：

- 只改被选中的那个渠道，其他渠道与 `enabled_models` 原样保留。
- 中途取消（Ctrl-C / 空输入）不写文件。
- 保存后立即按新配置重建 Agent，并切到默认模型。

## `/model`：模型切换

候选来自「已配置的渠道 × 模型」经 `enabled_models` 过滤后的范围。

| 输入 | 行为 |
|---|---|
| `/model` | 列表选择，默认高亮当前模型 |
| `/model gw/gpt-4o` | 精确切换 |
| `/model gpt-4o` | 只有一个渠道有该模型时直接切换 |
| 同名模型分布在多个渠道 | 报歧义并列出 `渠道/模型` 候选，不切换 |
| 模型存在但不在 `enabled_models` 范围 | 提示检查 `enabled_models` |
| `/model next`、`/model prev` | 在范围内循环；不足两个时提示 |

切换成功即重建 Agent（主模型与同渠道备选一并重建）并落盘为默认模型；会话不变，历史继续可用。状态栏与补全同步更新。

`enabled_models` 目前只能手改 `secret.yaml`，CLI 不提供编辑入口；空值表示全部模型可切换。

## `/mode`：权限模式

| 模式 | 文件工具 | Shell | 说明 |
|---|---|---|---|
| `read-only`（默认） | `read_file` / `list_files` / `grep`（Agno `CodingTools`：正则、行号、`-C` 上下文、`--include`） | 无 | 工作目录为 cwd |
| `workspace-write` | 上一行 + `write_file` / `edit_file` / `move_file` | 有，按审批策略确认（默认每次） | 写入限定 cwd |
| `danger-full-access` | 上一行 + `delete_file` | 有，无需确认 | 文件工具以 `/` 为根 |

- `/mode` 不带参数时弹选择菜单，带参数时校验取值。
- 切换后重建 Agent；系统提示词里的「当前可用工具」由实际装配的工具生成，只读模式不会提到写文件与 shell。

### HITL 确认

`workspace-write` 下模型请求 shell 命令时，本轮暂停并逐个询问：

```
  ? run_shell_command {"args": ["ls", "-la"]}
? 允许执行？ (y/N)
```

- 默认 `N`；输入不可用或中断视为拒绝。
- 同一「工具 + 参数」在本会话内批准一次后不再询问（审批记忆）；换参数或换命令会重新询问。
- 拒绝会把拒绝结果回填给模型，本轮继续而不是报错。
- 确认后从暂停处继续执行，输出行标 `✔` 与耗时。
- 非交互模式（`-p` / `--mode json`）无法提问，一律拒绝并写日志；`json` 模式会先输出 `confirm_required`。

#### 审批策略 `boundary.command_approval`

| 值 | 行为 |
|---|---|
| `always`（默认） | 每条命令都问 |
| `dangerous` | 只问命中危险规则的命令；其余自动放行并记日志 |

规则表在 `boundary/danger.py`（18 条：递归删除、格式化、写块设备、关机重启、提权、递归改权限、下载即执行、覆盖远端历史、强杀进程、磁盘擦除、读密钥、远传文件、覆写系统路径、停系统服务、全局装包、PowerShell 破坏性动词等），命中即停并显示理由。

- 策略只作用于「本来就要确认的工具」，即 `workspace-write` 下的 shell 与 PowerShell；`read-only` 没有命令工具，`danger-full-access` 无审批，三档都不受此键影响。
- `dangerous` 不是沙箱：绝对路径、软链接、脚本内间接调用都拦不住，它只保留对不可逆操作的确认。
- 改键立即生效，不重建 Agent（`/config boundary.command_approval dangerous`）。
- 非交互模式下 `dangerous` 让安全命令直接执行，危险命令仍被拒绝（`json` 输出 `confirm_required`）。

### 工具运行上限

| 项 | 值 |
|---|---|
| shell 超时 | 120 秒，超时后杀整个进程组；长任务改用后台 |
| 后台任务 | `run_shell_command(background=true)` 返回 job id，`job_output` 轮询状态与输出，`job_kill` 终止；轮询制，无守护进程；**状态只在当前进程内**，输出缓冲上限 1MB、已结束 job 保留 20 条，进程退出时未结束的 job 被终止，磁盘不留任何文件 |
| shell 输出 | 前台最多 1MB，只回最后 100 行 |
| PowerShell | 仅当系统存在 `pwsh`/`powershell` 时装配；`workspace-write` 下每次执行需确认，`danger-full-access` 直接执行；120 秒超时、1MB 输出上限 |
| 大结果卸载 | 超过 16k 字符的工具结果落 AgentFS，上下文只留信封；`read_result` 分页取回、`search_result` 检索 |
| 天气查询 | 10 秒超时 |
| 文件工具 | 单文件 2000 行 / 200KB |

## `/usage`：用量与花费

`/usage` 展示今天、`/usage week` 本周、`/usage month` 本月；周期按自然日/周（周一起）/月，本地时区。

```
今天 2026-11-18 · 用量与花费
  渠道      模型              输入   输出  缓存读    合计    金额
  --------  --------------  ------  -----  ------  ------  ------
  deepseek  deepseek-flash  128.0k  42.0k  980.0k  170.0k  $0.095
  tokenhub  gpt-6-luna       18.0k   6.4k       0   24.4k  $0.022
  --------  --------------  ------  -----  ------  ------  ------
  合计                      146.9k  48.5k  980.0k  195.4k  $0.116
```

- 行是 `(渠道, 模型)`，按 `输入 + 输出` 从高到低；没用过的模型不出现。
- `合计` 是输入 + 输出（与 Agno `total_tokens` 同义）；缓存读单列，不并入合计，
  避免与「prompt_tokens 已含缓存」的厂商口径重复计数。全为 0 时该列不显示。
- 金额按 `secret.yaml` 里的价目表在**入账时**算好并冻结；改价不影响历史。
- 未定价（渠道未知或缺价）的记录金额显示 `?`，表尾计数，合计金额不含它们。
- 每次 `/usage` 先把新出现的终态 run 同步进账本；同步失败只提示，不影响已有数据。

## `/session` 与 `/new`

- 会话 id 是 uuid 前 8 位，状态栏左侧显示。
- 每次运行都会把「目录 → 会话」写进 `sessions.db` 的索引表 `aaa_cwd_session`，所以 `-c` 续接的是「这个目录上次用的会话」。
- 启动期也可以用 `-c`（当前目录最近会话）或 `-r <id 前缀>` 直接进入指定会话。
- `/session` 每行格式 `标题 · id · 更新时间`，按更新时间倒序，最多 20 条。
- 会话标题在首条消息后由独立的一次模型调用生成，格式 `TAG: summary`（TAG 为 3–5 个大写字母，摘要不超过 12 词），失败则保持未命名。
- 切换会话只改当前会话 id 并更新索引，不重建 Agent；`/new` 分配新 id，旧会话留在库里。

## 上下文与压缩

- 压缩阈值 = 窗口 − max(窗口 15%, 16384 tokens)，窗口来自渠道配置里该模型的 `context_window`（缺省 1M）。
- 设了阈值后压缩接管回放窗口：每轮发送「上次折叠之后的全部轮次」，`num_history_runs` 不再限制回放，只决定保留尾的轮数（15）。
- 保留尾还有体积上限 `min(阈值/(1+最小折叠比), (阈值−头部占用)/2)`；最小折叠比 2.0，超限时减少保留轮数，切点向用户轮回退，不落在工具调用与结果之间。
- 折叠时被替换的历史原文写入会话库归档；出现第一次折叠后，模型多一个 `search_compacted_history` 工具，可按关键字检索被折叠的原文。
- 摘要预算 10k tokens，超预算按行截尾；折叠后剩余内容不足以缩小时拒绝折叠（`enforce_min_fold_ratio`），不写入空摘要。
- 工具结果超过 16k 字符时由 Agno 卸载：上下文里是带 id 的 `<result>` 信封加首尾预览，全文存 AgentFS，模型用 `read_result` 分页取回、`search_result` 检索。损坏或超配额的写入会返回“未存”信封并说明原因。
- 供应商报上下文超长时先折叠一次再重试（`on_context_overflow`）。
- `/compact` 手动压缩；结果按状态说明——已折叠、无可折叠历史、无内容可折叠、折叠不划算、摘要生成失败，都不算报错。
- 状态栏右侧进度条：百分比、压缩阈值位置的 `╎───┃` 标记、右端窗口上限。输入 token 数来自上一次模型请求完成事件上报的 `input_tokens`。

## 界面

- 提示符 `❯`（Windows 退化为 `>`），光标为浅蓝色。
- 补全：`/` 开头补全命令，`/model ` 之后补全 `渠道/模型` 与 `next`/`prev`。
- 状态栏：`session <id> · <渠道>/<模型> · <模式> · <cwd> · <上下文进度条>`，cwd 在 home 下显示为 `~`。
- 输出符号：`✔` 成功、`✘` 失败/错误、`·` 工具开始、`⎋` 生成中、`▸` 会话标题。Windows 控制台缺字，全部退化为 ASCII（`+`、`x`、`-`、`~`、`>`）。

## 运行期错误

| 现象 | 查看 |
|---|---|
| 模型调用失败 | 终端打印 `✘ <错误>`；完整堆栈在 `~/.aaa/logs/aaa.log` 的 `aaa` logger |
| 工具调用失败 | 工具行标 `✘` 与耗时，错误作为工具结果回填给模型 |
| 渠道探查失败 | 向导内提示具体异常，随后转入手输模型 |
| 会话库过大 | 启动时日志告警，需手动归档 |

`stream_run` 捕获异常后 REPL 继续，不会退出进程。
