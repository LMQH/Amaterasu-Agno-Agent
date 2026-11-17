"""config.toml：可调设置的键表、读写与校验。

程序是唯一写入方：用户通过 `/config` 修改，界面上不暴露文件本身。
文件缺失、缺键或含未知键时回落本节声明的默认值；非法值不静默采用，记入
`Settings.warnings` 由 `cli` 提示。
"""

import json
import tomllib
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from .paths import CONFIG_FILE
from ..boundary.policy import APPROVAL_STRATEGIES, MODES

# 生效方式：
#   runtime   —— 改完立即重建 Agent（模型、上下文、工具、记忆）
#   immediate —— 下一次使用时生效，不必重建
#   restart   —— 进程级设置，下次启动生效
APPLY_RUNTIME = "runtime"
APPLY_IMMEDIATE = "immediate"
APPLY_RESTART = "restart"


def _modes() -> Tuple[str, ...]:
    """权限模式名单的唯一来源在 boundary。"""
    return tuple(MODES)


def _approval_strategies() -> Tuple[str, ...]:
    """审批策略名单的唯一来源在 boundary。"""
    return tuple(APPROVAL_STRATEGIES)


@dataclass(frozen=True)
class Key:
    """一个可配置项：路径、默认值、类型、界面说明与校验范围。"""

    path: str
    default: Any
    kind: str
    label: str
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    choices: Optional[Callable[[], Tuple[str, ...]]] = None
    apply: str = APPLY_RUNTIME

    @property
    def group(self) -> str:
        return self.path.split(".", 1)[0]

    @property
    def short(self) -> str:
        return self.path.split(".", 1)[1]


# 键表顺序即 `/config` 菜单顺序。默认值与 `boundary.MODES[0]` 必须一致。
KEYS: Tuple[Key, ...] = (
    Key("memory.enabled", True, "bool", "启用记忆（Agno 原生记忆，含注入与工具）"),
    Key("memory.user_id", "default", "str", "记忆归属的用户 id"),
    Key("memory.delete_memories", True, "bool", "允许模型删除单条记忆"),
    Key("memory.clear_memories", True, "bool", "允许模型清空全部记忆"),
    Key("context.history_runs", 15, "int", "保留的尾轮数", minimum=1, maximum=200),
    Key("context.compaction_budget", 10_000, "int", "压缩后保留的 token 预算", minimum=0),
    Key("context.threshold_ratio", 0.85, "float", "压缩阈值占窗口的比例", minimum=0.1, maximum=0.99),
    Key("context.threshold_reserve", 16_384, "int", "压缩阈值预留的 token", minimum=0),
    Key("model.fallbacks", 2, "int", "同渠道 fallback 模型数", minimum=0, maximum=10),
    Key("model.timeout", 120, "int", "模型请求超时（秒）", minimum=1),
    Key("model.retries", 2, "int", "模型请求重试次数", minimum=0, maximum=10),
    Key("model.retry_delay", 1.0, "float", "重试间隔（秒）", minimum=0),
    Key("model.default_context_window", 1_000_000, "int", "渠道未声明窗口时的默认值", minimum=1_000),
    Key("tools.shell_timeout", 120, "int", "shell 超时（秒）", minimum=1),
    Key("tools.shell_output_bytes", 1_000_000, "int", "shell 输出字节上限", minimum=100),
    Key("tools.weather_timeout", 10, "int", "天气查询超时（秒）", minimum=1),
    Key("tools.shell_tail", 100, "int", "shell 返回的末尾行数", minimum=1),
    Key("tools.file_max_lines", 2_000, "int", "文件工具行数上限", minimum=1),
    Key("tools.file_max_length", 200_000, "int", "文件工具字符上限", minimum=1),
    Key("boundary.default_mode", "read-only", "str", "新会话的默认权限模式",
        choices=_modes, apply=APPLY_RESTART),
    Key("boundary.command_approval", "always", "str",
        "命令类工具的审批策略（always=每条都问，dangerous=仅危险命令）",
        choices=_approval_strategies, apply=APPLY_IMMEDIATE),
    Key("log.max_bytes", 5_000_000, "int", "日志轮转字节数", minimum=1_000, apply=APPLY_RESTART),
    Key("log.db_warn_bytes", 200_000_000, "int", "会话库告警字节数", minimum=1_000_000, apply=APPLY_RESTART),
    Key("log.level", "INFO", "str", "日志级别", apply=APPLY_RESTART),
    Key("ui.toolbar_width", 48, "int", "状态条目录显示宽度", minimum=8, maximum=200, apply=APPLY_IMMEDIATE),
    Key("ui.bar_min_width", 24, "int", "上下文条最小宽度", minimum=8, maximum=200, apply=APPLY_IMMEDIATE),
    Key("ui.bar_max_width", 80, "int", "上下文条最大宽度", minimum=8, maximum=400, apply=APPLY_IMMEDIATE),
    Key("sessions.id_length", 8, "int", "会话 id 字符数", minimum=4, maximum=32, apply=APPLY_IMMEDIATE),
    Key("sessions.title_length", 60, "int", "会话标题最大字符数", minimum=8, maximum=200, apply=APPLY_IMMEDIATE),
    Key("sessions.list_limit", 20, "int", "`/session` 列表条数", minimum=1, maximum=500, apply=APPLY_IMMEDIATE),
    Key("sessions.search_limit", 200, "int", "会话查找扫描条数", minimum=1, maximum=5_000, apply=APPLY_IMMEDIATE),
)

BY_PATH: Dict[str, Key] = {key.path: key for key in KEYS}

_TRUE = {"true", "1", "yes", "on", "y"}
_FALSE = {"false", "0", "no", "off", "n"}


def coerce(key: Key, raw: Any) -> Any:
    """把输入转成配置项的类型；不合法时抛 ValueError。"""
    if key.kind == "bool":
        if isinstance(raw, bool):
            return raw
        text = str(raw).strip().lower()
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
        raise ValueError(f"{key.path} 需要布尔值（true/false）")
    if key.kind in ("int", "float"):
        try:
            value = int(str(raw).strip()) if key.kind == "int" else float(str(raw).strip())
        except ValueError:
            raise ValueError(f"{key.path} 需要{'整数' if key.kind == 'int' else '数字'}")
        if key.minimum is not None and value < key.minimum:
            raise ValueError(f"{key.path} 不能小于 {_fmt(key.minimum)}")
        if key.maximum is not None and value > key.maximum:
            raise ValueError(f"{key.path} 不能大于 {_fmt(key.maximum)}")
        return value
    value = raw if isinstance(raw, str) else str(raw)
    value = value.strip()
    if key.choices is not None:
        allowed = key.choices()
        if value not in allowed:
            raise ValueError(f"{key.path} 只能是：{'、'.join(allowed)}")
    return value


def _fmt(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


class Settings:
    """一份生效中的设置；不可变语义由调用方维护，写入都经 `set` + `save`。"""

    def __init__(self, values: Optional[Dict[str, Any]] = None) -> None:
        self._values: Dict[str, Any] = {key.path: key.default for key in KEYS}
        self.warnings: List[str] = []
        for path, value in (values or {}).items():
            key = BY_PATH.get(path)
            if key is None:
                self.warnings.append(f"未知配置项已忽略：{path}")
                continue
            try:
                self._values[path] = coerce(key, value)
            except ValueError as exc:
                self.warnings.append(f"{exc}，已用默认值 {_fmt(key.default)}")

    def get(self, path: str) -> Any:
        return self._values[path]

    def set(self, path: str, raw: Any) -> Key:
        """校验并写入；不落盘（由 `save` 负责）。"""
        key = BY_PATH.get(path)
        if key is None:
            raise ValueError(f"未知配置键：{path}")
        self._values[path] = coerce(key, raw)
        return key

    def groups(self) -> List[str]:
        seen: List[str] = []
        for key in KEYS:
            if key.group not in seen:
                seen.append(key.group)
        return seen

    def keys_of(self, group: str) -> List[Key]:
        return [key for key in KEYS if key.group == group]

    def describe(self, path: str) -> str:
        key = BY_PATH[path]
        text = key.label
        if key.kind in ("int", "float") and (key.minimum is not None or key.maximum is not None):
            low = _fmt(key.minimum) if key.minimum is not None else "-"
            high = _fmt(key.maximum) if key.maximum is not None else "-"
            text += f"（{low} ~ {high}）"
        if key.choices is not None:
            text += f"（{'、'.join(key.choices())}）"
        return text

    def to_dict(self) -> Dict[str, Dict[str, Any]]:
        nested: Dict[str, Dict[str, Any]] = {}
        for key in KEYS:
            nested.setdefault(key.group, {})[key.short] = self._values[key.path]
        return nested

    def to_toml(self) -> str:
        lines = ["# aaa 配置：由程序维护，修改请用 /config。"]
        for group, table in self.to_dict().items():
            lines.append("")
            lines.append(f"[{group}]")
            for name, value in table.items():
                lines.append(f"{name} = {_toml_value(value)}")
        return "\n".join(lines) + "\n"


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    return json.dumps(value, ensure_ascii=False)


def load_settings() -> Settings:
    """读取 config.toml；文件缺失、不可解析或含非法值时回落默认并记警告。"""
    settings = Settings()
    if not CONFIG_FILE.exists():
        return settings
    try:
        data = tomllib.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        settings.warnings.append(f"config.toml 无法解析（{exc}），已全部使用默认值")
        return settings
    flat: Dict[str, Any] = {}
    for group, table in data.items():
        if not isinstance(table, dict):
            settings.warnings.append(f"未知配置项已忽略：{group}")
            continue
        for name, value in table.items():
            flat[f"{group}.{name}"] = value
    merged = Settings(flat)
    merged.warnings = settings.warnings + merged.warnings
    return merged


def save(settings: Settings) -> None:
    """全量写回 config.toml（原子替换）。"""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = CONFIG_FILE.with_suffix(".tmp")
    temp.write_text(settings.to_toml(), encoding="utf-8")
    temp.replace(CONFIG_FILE)
