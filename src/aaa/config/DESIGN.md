# config — 配置

## 边界与目标

两个文件、两类事实：

- `~/.aaa/secret.yaml`：渠道（协议、地址、api_key、模型清单）、默认模型、可切换范围。密钥只在这里。
- `~/.aaa/config.toml`：其余所有可调设置（记忆、上下文、模型参数、工具上限、默认权限模式、日志、界面、会话语义）。

`secret.yaml` 只做 IO、归一与 v1→v2 迁移；`config.toml` 是程序的数据文件——用户不手改，改动一律从 `/config` 走，程序负责写回。

## 拥有者与不变量

- 路径只在这里定义（`paths.py`）：家目录、数据、日志、`sessions.db`、`secret.yaml`、`config.toml`、输入历史。
- 落盘 schema 恒为 v2：`version`、`default: {provider, model}` 两键、`enabled_models`、`providers` 映射。
- `secret.yaml` 读时不改用户文件：v1 只内存归一，下次保存才落 v2；保存原子且 `0600`。
- `secret.yaml` 存在但读不出有效配置时抛 `ConfigError`，绝不进向导（向导会覆盖原文件）；只有文件不存在才视为未配置。
- `config.toml` 的键表是唯一来源（`settings.py` 的 `KEYS`）：路径、默认值、类型、范围、界面说明、生效方式都在一处。新增可调项只改这张表。
- `config.toml` 全量写回（原子替换），不做稀疏覆盖；文件缺失、缺键或含未知键时回落默认值，非法值回落默认并记入 `Settings.warnings` 由 `cli` 打印。
- 生效方式三分：`runtime`（立即重建 Agent）、`immediate`（下次使用生效）、`restart`（下次启动生效）。

## 对外接口

- `load_config(settings) -> Optional[Dict]`：`None` 表示文件不存在；不可解析或无可用渠道抛 `ConfigError`。
- `save_config(config)`：写 `secret.yaml`（0600 原子）。
- `normalize_config(data, settings)`：v1 渠道 id 取主机名首段（`api.deepseek.com` → `deepseek`），冲突加序号；窗口缺省取 `model.default_context_window`；默认模型失效时回落到第一个渠道的第一个模型。
- `probe_models(base_url, api_key)`：`GET /models`，15 秒超时；读不到窗口记 0 交由用户手填。
- `Settings`：`get(path)`、`set(path, raw)`（校验并抛 `ValueError`）、`groups()`、`keys_of(group)`、`describe(path)`、`to_toml()`。
- `load_settings()` / `save(settings)`。

## 已否决做法

- 读到 v1 立即回写：启动即改用户文件，解析/网络异常时可能写坏配置 → 内存归一、保存才迁移。
- 直接覆盖写 `secret.yaml`：中途失败留半截文件 → 临时文件 + `replace`，落盘前设 `0600`。
- 把可调设置塞进 `secret.yaml`：密钥文件与常规配置混在一起，无法单独轮换 → 拆成 `config.toml`。
- 用一个通用 TOML 写库：`config.toml` 只有两层表与标量，自写约 40 行序列化即够，不引入新依赖。
- 让用户手改 `config.toml`：键多、类型与范围需要校验，手改容易写出程序不认的值 → 只经 `/config`，程序写回。
