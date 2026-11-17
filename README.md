# aaa

项目定位：待定（未提供业务信息，不编造）。当前形态是跑在终端里的 Agno agent harness，支持多个模型渠道与切换。

## 目录

- `AGENTS.md` — 工作协议：开发机制、设计原则、代码规则、验证要求、授权边界
- `HANDOFF.md` — 当前工作线做到哪、卡在哪、下一步
- `src/aaa/` — 代码，按模块分目录：`config`、`model`、`runtime`、`context`、`boundary`、`tools`、`memory`、`usage`、`sessions`、`cli`；每个模块的边界与不变量见其 `DESIGN.md`
- `docs/architecture.md` — 总架构：五层职责、模块依赖、铁律、设计思想
- `docs/cli.md` — 当前 CLI 功能说明：命令、权限模式、HITL、上下文与输出
- `docs/memo.md` — 中远期备忘：暂不执行的计划与各自的触发条件
- `tests/` — 单元回归 `test_units.py` 与真实渠道路径 `e2e.py`，说明见 `tests/README.md`

## 运行

依赖由 `pyproject.toml` 声明、`uv.lock` 锁定，装环境只做一次：

```bash
uv sync --frozen                        # 按锁建 .venv，不发散解析
PYTHONPATH=src .venv/bin/python -m aaa            # 交互 REPL
PYTHONPATH=src .venv/bin/python -m aaa -p "..."   # 非交互单轮
```

启动参数、非交互输出与状态语义见 `docs/cli.md`。

设置分两个文件：`~/.aaa/secret.yaml`（0600）只放渠道、密钥与默认模型；`~/.aaa/config.toml` 放其余全部可调项（记忆、压缩、模型超时、工具上限、默认权限模式、命令审批策略、日志、界面、会话）。`config.toml` 由程序维护，改动一律用 `/config`（无参进菜单，`/config <键> <值>` 精确修改），程序校验后写回。

依赖闭包由 `uv.lock` 决定（48 条记录，含 Windows/emscripten 专用项；本机实装 45 个包），Python 要求 `>=3.11,<3.14`（实测 3.13.12）。直接依赖只有五个：`agno[openai,sqlite]`、`tiktoken`、`pyyaml`、`prompt_toolkit`、`questionary`；`openai`/`sqlalchemy`/`aiosqlite` 来自 agno 的 extra，裸 `agno==` 装不出可用环境。`tiktoken` 缺失时压缩阈值退回 `字符数/4` 估算，中文场景低估 1.7–3 倍，压缩会被显著推迟甚至长期不触发。`[tool.uv] constraint-dependencies` 把五个传递依赖约束在实测版本上，改动它们等于换基线，需重跑 `tests/e2e.py`。首次启动进入渠道配置，数据与日志落在 `~/.aaa/`。

## 渠道与模型

渠道写在 `~/.aaa/secret.yaml`（0600）：一个渠道 = 一个端点，`api` 决定用哪个 Agno 模型类。

```yaml
version: 2
default:
  provider: deepseek
  model: deepseek-chat
enabled_models: []          # 可切换范围；空表示全部，模式同时匹配 provider/model 与裸 model
providers:
  deepseek:
    name: DeepSeek
    api: deepseek           # 发 thinking 参数，适合官方端点
    base_url: https://api.deepseek.com
    api_key: sk-...
    models:
      - id: deepseek-chat
        context_window: 128000
        cost:                       # 可选：美元 / 百万 token，供 /usage 计价
          input: 0.3
          output: 1.2
          cache_read: 0.006
          cache_write: 0
          # off_peak:               # 可选：低谷价（本地时间窗口，允许跨午夜）
          #   multiplier: 0.5
          #   windows: [["00:30", "08:30"]]
  gw:
    name: 公司网关
    api: openai-completions # 通用 OpenAI 兼容端点，不发私有参数
    base_url: https://gw.example.com/v1
    api_key: sk-...
    models:
      - id: gpt-4o
        context_window: 128000
        max_tokens: 8192
```

- 模型身份是 `(provider, model_id)` 一对，显示与输入都用 `provider/model_id`。
- `/model` 列出可切换模型；`/model <引用>` 精确切换，同名跨渠道时要求带渠道前缀；`/model next` / `prev` 在范围内循环。
- `/provide` 按渠道增改，未编辑的渠道原样保留。
- v1 配置（`providers` 为列表、`default_model` 单键）在读取时自动归一，下次保存落 v2。
