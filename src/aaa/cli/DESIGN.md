# cli — 模块设计

## 边界与目标

入口、启动参数、REPL 状态、斜杠命令、渲染与事件消费。三件事分开：`app` 决定跑什么（分派、底部状态条、退出码），`state` 持有进程内可变状态，`run` 把 Agno 事件流转成三种输出形态并处理 HITL。`ui`/`completer` 只管终端表现与补全，不碰状态。

## 拥有者与不变量

- `AppState` 是进程内唯一可变状态：`config`（secret.yaml）、`settings`（config.toml）、`Catalog`、`(provider, model_id)`、`mode`、`agent`、`session_id`、`completer`、`context_tokens`、`approved`。每个事实只有一个写入点。
- 换模型只经 `set_model`，顺序固定：`require` 校验 → 重建 agent → 落盘默认值；校验失败不进入半状态。换模式只经赋 `mode` + `rebuild_agent`。两者都清 `context_tokens`，并由 `rebuild_agent` 按 `scope` 重造补全器。
- 改配置只经 `/config`：校验 → 落盘 `config.toml` → 按生效方式处理（`runtime` 重建 Agent、`immediate` 等下次使用、`restart` 提示重启）。`apply_settings` 同时按新配置重建 `Catalog`。
- 审批签名 = 工具名 + `sort_keys` 后的参数 JSON；同一签名在本会话内只问一次。
- `user_id` 从 `memory.user_id` 取，经 `stream_run` 传给 `agent.run` 与 `continue_run`；记忆归属只由这一处决定。
- 非交互无审批能力：`PlainEmitter`/`JsonEmitter` 默认拒绝，`json` 先输出 `confirm_required` 行；显式 `--allow-shell` 时只放行 `run_shell_command`（`json` 输出 `confirm_approved`）。`-p` 的 stdout 只有正文，工具与运行期错误进 `~/.aaa/logs/aaa.log`。
- 退出码固定：0 成功、1 运行失败、2 用法/配置问题、130 被中断。
- 首启无配置：交互模式进入向导，非交互模式直接报错退出，不落半份配置；`secret.yaml` 存在但读不出来时一律报错退出（`ConfigError`），绝不进向导覆盖原文件。
- 退出 REPL 时清空 `agent.model.api_key`（密钥只留在 0600 的 `secret.yaml`）。
- `configure` 只改一个渠道，未编辑的渠道与 `enabled_models` 原样保留；API Key 留空沿用旧值。

## 对外接口

- `parse_args(default_mode, argv) -> Options`：位置消息、`-p/--print`、`--mode interactive|print|json`（与 `-p` 互斥）、`-m/--model`、`--permission`（默认取 `boundary.default_mode`）、`-c` 与 `-r`（互斥）、`--allow-shell`。
- `main(argv)`、`run_once(state, message, output, allow_shell) -> int`、`handle_command(state, text) -> bool`（True 表示已处理，False 交给模型）、`configure(existing, settings) -> Optional[Dict]`。
- `stream_run(agent, text, session_id, approved, emitter, user_id) -> Dict`：返回 `{content, tokens, duration, context_tokens, error, cancelled}`。`RunPausedEvent` 后走 `continue_run(run_id, requirements, session_id)`（该调用必须带 `session_id`）；`KeyboardInterrupt` 时调 `cancel_run` 并标记取消。
- `HumanEmitter` / `PlainEmitter` / `JsonEmitter`：只实现 `event(kind, **data)`、`ask_approval(name, args)`、`close()`。
- `context_bar` / `StatusLine` / `GLYPH` / `PT_STYLE` / `SlashCompleter`（命令、模型引用与 `/config` 键补全）。

## 需求（计划，未实现）

- **`/clear`**：清空当前会话的上下文、保留会话 id。与 `/new`（换新会话，id 变）和 `/compact`（压缩，内容仍在）是三种不同语义。CLI 整体尚未定版，实现时与 `-c` 的会话索引语义一起复核。
- **CLI 面整体待定版**：命令集合（含会话相关命令）、非交互审批策略、输出形态在此轮一并收口；新增命令必须先落到本节，再进代码。

## 已否决做法

- 每种输出形态各写一套事件循环：事件分类与审批逻辑必然分叉 → 共用 `stream_run`，emitter 只决定表现与「能否确认」。
- 在提示词里手写可用工具：与实际工具集分叉 → 用 `boundary.tool_names` 从装配结果生成。
- 非交互模式下把工具活动打到 stdout：会污染正文与 json 事件流 → 一律进日志。
- Windows 用 Nerd Font 符号：控制台字体缺字 → `GLYPH`/`ICONS` 在 `os.name == "nt"` 时退回 ASCII。
