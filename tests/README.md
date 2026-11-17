# 测试体系

分三层，各管一段，不互相替代：

| 层 | 文件 | 跑什么 | 成本 |
|---|---|---|---|
| 单元 | `tests/test_*.py`（含 `fixtures.py`） | 模块契约 + **假模型驱动的 Agent 循环**（工具往返、HITL 暂停/确认/拒绝、压缩参数派生、配置校验、会话索引、审批签名、用量账本：计价与峰谷窗口、同步幂等、未定价补算、报表排序） | 毫秒级，零网络 |
| 端到端 | `tests/e2e.py` | 真实 CLI 进程 + 真实渠道 + 真实工具，断言 stdout/产物/日志/库 | 分钟级，几十 token |
| 交互 | `tests/pty_cases.py` | PTY 驱动 REPL：HITL 审批、`/provide` 向导 | 秒级，一次真实探查 |

统一入口：

```bash
./tests/run.sh              # 离线单测（固定 TZ/LC、清代理、-W error）
./tests/run.sh e2e           # 追加 e2e 全量
./tests/run.sh e2e --suite p0 --pty
```

`fixtures.FakeModel` 按脚本回放 `ModelResponse`（`text()` / `tool_call()`），只实现 `invoke` 及流式/异步变体；消息拼装、工具执行、会话写入仍由 Agno 完成，因此测的是真实循环而非另一套实现。

# 端到端测试计划

目的：把「只打过桩」的链路用真实渠道跑一遍，闭合 Coding Agent 的最小可交付闭环，并记录仍然测不了的部分。

脚本：`tests/e2e.py`（stdlib + PyYAML，无 pytest 依赖）。计划是脚本的唯一说明，脚本是计划的唯一执行入口。

## 前置

| 项 | 要求 |
|---|---|
| 解释器 | 仓库根执行 `uv sync --frozen` 后的 `.venv/bin/python`，或 `AAA_PYTHON=<python>` 指定 |
| 配置 | `~/.aaa/secret.yaml` 存在，至少一个可用渠道；脚本复制到临时 `HOME` 后按需改动，不碰真实配置 |
| 网络 | 本机需要代理；脚本自动剔除 `ALL_PROXY`/`all_proxy`（验证环境未装 socksio），保留 `HTTPS_PROXY` |
| tokenizer | 需要 `tiktoken`；缺失时 token 计数退回 `字符数/4`，真实历史实测低估 3.17×，压缩触发会晚约 3 倍。脚本在跑 P1 前检查，缺失直接报错 |
| 成本 | P0 十条约 70–100 秒；P1.7/P1.8 各最多 10–12 轮长输出，输入每轮约 +540 token |

## 渠道基线（本次配置）

| 渠道 | api | 模型 | 窗口 |
|---|---|---|---|
| `tokenhub` | `openai-completions` | `deepseek-flash`、`gpt-6-luna` | 1048576 / 131072 |
| `deepseek` | `deepseek` | `deepseek-flash`、`deepseek-v4-pro` | 1048576（官方 `/models` 上报） |

`deepseek-flash` 同名跨渠道，因此裸 id 解析应返回 `Ambiguous`——这是 P0 之外的一条已手工验证事实，脚本不重复。

## 用例

### P0 闭环（默认执行）

| # | 目标 | 步骤 | 断言 |
|---|---|---|---|
| P0.1 | 真实工具调用 | read-only，临时工作目录放 `data.txt`，要求模型读取 | 输出包含文件标记 |
| P0.2 | 真实写入 | `danger-full-access`，要求写 `out.txt` | 文件存在且含标记 |
| P0.3 | 非交互拒绝 shell | `workspace-write`，要求执行 `echo` | 日志含「非交互模式无法确认工具」与 `run_shell_command`；进程正常结束 |
| P0.4 | 多轮续接 | json 模式第一轮埋标记并取 `session_id`，`-r` 追问 | 续接后答出标记 |
| P0.5 | JSON 事件流 | 要求列目录 | 出现 `tool_start`；`result` 带 `session_id` 与非零 `tokens` |
| P0.6 | 错误路径 | 临时配置换成坏 key | 退出码非 0；日志含 `ERROR` |
| P0.7 | 损坏配置不被覆盖 | 把 `secret.yaml` 写成非法 YAML 后启动 | 退出码 2；提示解析错误；文件字节不变 |
| P0.8 | `--allow-shell` 放行 | `workspace-write` + `--allow-shell`，要求执行 `echo` | 命令执行、结果回填；日志无拒绝记录 |
| P0.9 | grep 工具 | read-only，要求用 grep 找 `build_agent` 定义位置（Agno `CodingTools`） | 答出 `src/app.py`（正则检索闭环） |
| P0.10 | 大结果卸载可回读 | read-only，1500 行文件，要求读最后一行 | 会话库出现 `<result id=` 与 `read_result`；答出末行标记 |

### P1 治理（默认执行）

| # | 目标 | 步骤 | 断言 |
|---|---|---|---|
| P1.7 | 压缩触发 | 临时配置把窗口压到 20000（阈值 3616），连跑最多 10 轮长输出（每轮 60 行；输入每轮约 +540 token） | 日志出现 `Auto-compacting` |
| P1.8 | 归档检索 | 埋标记 → 与 P1.7 同款长输出最多 12 轮直到折叠 → 追问标记 | 能答出；日志出现 `search_compacted_history` 则记为强证据，否则记「仍在保留尾内」 |

### P2 交互面（`--pty`，默认不跑）

| # | 目标 | 步骤 | 断言 |
|---|---|---|---|
| P2.11 | HITL 真实确认 | PTY 起 REPL → `/mode workspace-write` → 要求执行 `echo hitl-ok` → 应答 `y` | 出现「允许执行」，审批后输出 `hitl-ok` |
| P2.12 | `/provide` 真实向导 | 空 `HOME` 起 REPL，按提示输入渠道 id、协议、URL、Key，等真实探查后勾选模型 | `secret.yaml` 落盘 0600、渠道与模型正确、默认模型可用 |

P2 实现在 `tests/pty_cases.py`，由 `e2e.py --pty` 导入。

## 单元回归

`tests/test_*.py`，不联网、不建真实 `HOME`（需要路径的用例用临时目录），运行 `./tests/run.sh`。

覆盖：

- `Catalog`：resolve 四态、scope、fallbacks。
- `boundary`：三档能力/确认/隔离声明、`signature` 键序无关、`PolicySource` 替换后工具面变化。
- `tools`：grep 注册与 `search_content` 退场、后台 job 生命周期（启动/轮询/退出码/终止/非法 id/状态不落盘）、PowerShell 条件装配与参数拼装。
- `sessions`：目录→会话索引（未知目录、覆盖推进、`seq` 单调）。
- `config.settings`：默认值、类型/越界回落并告警、未知键忽略、不可解析文件、落盘回读。
- `context.params`：阈值按 `max(W×(1-ratio), reserve)` 派生、最小为 1。
- **Agent 循环（假模型）**：工具往返返回最终答复、HITL 暂停 → 确认续跑、拒绝理由回填给模型。

## 已知测不了（脚本不包含，别当已覆盖）

| 项 | 原因 |
|---|---|
| fallback 真实切换 | 同渠道共享 `base_url`，无法让主模型单独失败；需要注入 429/5xx 或按模型给独立端点 |
| 上下文窗口溢出恢复（`on_context_overflow`） | 需要真实超长请求；1M 窗口下成本不可接受 |
| PowerShell 工具 | 本机没有 `pwsh`/`powershell`：只验证了“不存在时不装配”与参数拼装，未在 Windows 实跑 |
| `-c`（按目录续接） | 端到端无用例；`-c` 依赖的目录→会话索引仅有单测覆盖（P0.4 走 `-r`，不经过索引） |
| 记忆、只读归因 | 未实现 |
| 多渠道路径歧义 | 已手工验证（`deepseek-flash` → `Ambiguous`），未入脚本以免重复成本 |
| 长命令后台化 | 未实现，>120s 即杀进程组 |

## 清理

每个用例的 `HOME` 与工作目录建在系统临时目录下，脚本不删除（删除受团队策略限制，需人工确认清单后处理）。`~/.aaa/data/sessions.db` 不被脚本写入。

## 审批后执行

```bash
.venv/bin/python tests/e2e.py --list      # 只列用例，零请求
.venv/bin/python tests/e2e.py             # P0 + P1
.venv/bin/python tests/e2e.py --suite p0  # 只跑闭环
.venv/bin/python tests/e2e.py --pty       # 追加交互面
```
