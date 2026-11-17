"""斜杠命令：渠道编辑、模型切换与命令分派。"""

import copy
import re
from typing import Dict, List, Optional

import questionary

from ..boundary.policy import MODES
from ..config.loader import CONFIG_VERSION, SECRET_FILE, probe_models, save_config
from ..config.settings import APPLY_RESTART, APPLY_RUNTIME, BY_PATH, save as save_settings
from ..model.catalog import Ambiguous, NotFound, Resolved
from ..model.provider import API_CLASSES, DEFAULT_API
from ..sessions.query import list_sessions, new_session_id, session_label
from ..usage import ledger as usage_ledger
from ..usage import report as usage_report
from .state import AppState
from .ui import GLYPH, UI_STYLE, display_width, pad, print_help

# 渠道 id：用作 `/model <id>/<model>` 的前缀，只允许小写字母、数字与连字符。
CHANNEL_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]*")
NEW_CHANNEL = "＋ 新增渠道"

API_LABELS = {
    "deepseek": "DeepSeek 原生（发 thinking 参数）",
    "openai-completions": "OpenAI 兼容（通用端点）",
}


def configure(existing: Optional[Dict], settings) -> Optional[Dict]:
    """渠道编辑器：选择或新增一个渠道，改完写回 secret.yaml。

    返回新配置；用户中途取消时返回 None，不改动已有文件。
    """
    base = copy.deepcopy(existing) if existing else {}
    providers: Dict[str, Dict] = base.get("providers") or {}
    print("\n渠道配置\n")

    provider_id = _choose_channel(providers)
    if provider_id is None:
        return None
    raw = providers.get(provider_id) or {}
    if provider_id == NEW_CHANNEL:
        provider_id = _ask_channel_id(providers)
        if not provider_id:
            return None
        raw = {}

    channel = _edit_channel(provider_id, raw)
    if channel is None:
        return None
    providers[provider_id] = channel

    default = _default_choice(providers, base.get("default"))
    if default is None:
        return None

    config = {
        "version": CONFIG_VERSION,
        "default": default,
        "enabled_models": [item for item in (base.get("enabled_models") or []) if isinstance(item, str)],
        "providers": providers,
    }
    save_config(config)
    print(f"已保存 {SECRET_FILE}")
    return config


def _choose_channel(providers: Dict[str, Dict]) -> Optional[str]:
    if not providers:
        return NEW_CHANNEL
    choices = [
        questionary.Choice(f"{pid}  ({raw.get('base_url')})", value=pid)
        for pid, raw in providers.items()
    ]
    choices.append(questionary.Choice(NEW_CHANNEL, value=NEW_CHANNEL))
    return questionary.select("编辑哪个渠道", choices=choices, style=UI_STYLE).ask()


def _ask_channel_id(providers: Dict[str, Dict]) -> Optional[str]:
    value = questionary.text("渠道 id（用作 /model 的前缀）", style=UI_STYLE).ask()
    value = (value or "").strip().lower()
    if not CHANNEL_ID_PATTERN.fullmatch(value):
        print("渠道 id 只能包含小写字母、数字与连字符。")
        return None
    if value in providers:
        print(f"渠道已存在：{value}")
        return None
    return value


def _edit_channel(provider_id: str, raw: Dict) -> Optional[Dict]:
    api = questionary.select(
        "协议",
        choices=[
            questionary.Choice(API_LABELS.get(name, name), value=name)
            for name in API_CLASSES
        ],
        default=raw.get("api") or DEFAULT_API,
        style=UI_STYLE,
    ).ask()
    if not api:
        return None

    default_url = raw.get("base_url") or (
        "https://api.deepseek.com" if api == DEFAULT_API else ""
    )
    base_url = questionary.text("Base URL", default=default_url, style=UI_STYLE).ask()
    if not base_url:
        return None

    old_key = raw.get("api_key") or ""
    hint = "API Key（已保存，留空沿用）" if old_key else "API Key"
    api_key = questionary.password(hint, style=UI_STYLE).ask()
    if api_key is None:
        return None
    api_key = api_key.strip() or old_key
    if not api_key:
        print("未提供 API Key，配置未保存。")
        return None

    previous = {item["id"]: item for item in raw.get("models") or []}
    discovered: List[str] = []
    detected: Dict[str, int] = {}
    print("正在探查可用模型 ...")
    try:
        discovered, detected = probe_models(base_url, api_key)
    except Exception as exc:
        print(f"探查失败：{exc}")

    if discovered:
        chosen = questionary.checkbox(
            "启用哪些模型（空格选择，回车确认）",
            choices=[
                questionary.Choice(model, value=model, checked=model in previous)
                for model in discovered
            ],
            style=UI_STYLE,
        ).ask()
    else:
        manual = questionary.text(
            "未探查到模型，请手动输入（逗号分隔）", style=UI_STYLE
        ).ask()
        chosen = [item.strip() for item in (manual or "").split(",") if item.strip()]
    if not chosen:
        print("未选择模型，配置未保存。")
        return None

    models: List[Dict] = []
    for model in chosen:
        old = previous.get(model) or {}
        default = str(
            old.get("context_window")
            or detected.get(model)
            or settings.get("model.default_context_window")
        )
        answer = questionary.text(
            f"{model} 的上下文窗口（tokens）",
            default=default,
            style=UI_STYLE,
        ).ask()
        entry = dict(old)
        entry["id"] = model
        entry["context_window"] = (
            int(answer) if answer and answer.isdigit() else int(default)
        )
        models.append(entry)

    return {
        "name": raw.get("name") or provider_id,
        "api": api,
        "base_url": base_url.rstrip("/"),
        "api_key": api_key,
        "models": models,
    }


def _default_choice(providers: Dict[str, Dict], current) -> Optional[Dict]:
    references = [
        f"{pid}/{item['id']}"
        for pid, raw in providers.items()
        for item in raw.get("models") or []
    ]
    if not references:
        return None
    keep = None
    if isinstance(current, dict):
        keep = f"{current.get('provider')}/{current.get('model')}"
    picked = keep if keep in references else None
    if picked is None:
        picked = questionary.select(
            "默认模型", choices=references, style=UI_STYLE
        ).ask()
    if not picked:
        return None
    provider, model_id = picked.split("/", 1)
    return {"provider": provider, "model": model_id}


def handle_command(state: AppState, text: str) -> bool:
    """处理斜杠命令；返回 True 表示已处理，False 表示这行交给模型。"""
    if text == "/help":
        print_help()
        return True

    if text == "/session":
        sessions = list_sessions(state.agent, limit=int(state.settings.get("sessions.list_limit")))
        if not sessions:
            print("暂无会话。")
            return True
        picked = questionary.select(
            "选择会话",
            choices=[questionary.Choice(session_label(s), value=s.session_id) for s in sessions],
            style=UI_STYLE,
        ).ask()
        if picked:
            state.session_id = picked
            state.context_tokens = None
            print(f"{GLYPH['ok']} Switched to session {state.session_id}")
        return True

    if text.startswith("/session "):
        target = text[len("/session "):].strip()
        if state.agent.get_session(session_id=target) is None:
            print(f"会话不存在：{target}")
            return True
        state.session_id = target
        state.context_tokens = None
        print(f"{GLYPH['ok']} Switched to session {state.session_id}")
        return True

    if text == "/new":
        state.session_id = new_session_id(state.settings)
        state.context_tokens = None
        print(f"{GLYPH['ok']} New session started")
        return True

    if text == "/provide":
        updated = configure(state.config, state.settings)
        if updated is not None:
            state.apply_config(updated)
            print(f"{GLYPH['ok']} Model: {state.model_ref.display}")
        return True

    if text == "/usage" or text.startswith("/usage "):
        _usage_command(state, text[len("/usage"):].strip())
        return True

    if text == "/compact":
        try:
            result = state.agent.compact(session_id=state.session_id)
        except Exception as exc:
            print(f"{GLYPH['fail']} {exc}")
            return True
        mark = GLYPH["ok"] if getattr(result, "compacted", False) else GLYPH["dot"]
        print(f"{mark} {getattr(result, 'message', result)}")
        if getattr(result, "compacted", False):
            state.context_tokens = None
        return True

    if text == "/config" or text.startswith("/config "):
        argument = text[len("/config"):].strip()
        _config_command(state, argument)
        return True

    if text == "/mode" or text.startswith("/mode "):
        argument = text[len("/mode"):].strip()
        if not argument:
            argument = questionary.select(
                "权限模式", choices=MODES, default=state.mode, style=UI_STYLE
            ).ask()
            if not argument:
                return True
        if argument not in MODES:
            print(f"未知模式：{argument}")
            return True
        state.mode = argument
        state.rebuild_agent()
        print(f"{GLYPH['ok']} Mode: {state.mode}")
        return True

    if text == "/model" or text.startswith("/model "):
        argument = text[len("/model"):].strip()
        scope = state.scope()
        if not scope:
            print("没有可切换的模型：检查 secret.yaml 的 providers 与 enabled_models。")
            return True

        if argument in ("next", "prev"):
            target = state.cycle_model(1 if argument == "next" else -1)
            if target is None:
                print("可切换的模型不足两个。")
                return True
            state.set_model(target.provider, target.model_id)
            print(f"{GLYPH['ok']} Model: {target.display}")
            return True

        if not argument:
            current = state.model_ref.display
            picked = questionary.select(
                "选择模型",
                choices=[ref.display for ref in scope],
                default=current if state.model_ref in scope else None,
                style=UI_STYLE,
            ).ask()
            if not picked:
                return True
            argument = picked

        result = state.catalog.resolve(argument, scope)
        if isinstance(result, Ambiguous):
            print(f"多个渠道都有 {argument}，请加渠道前缀：")
            for ref in result.candidates:
                print(f"  {ref.display}")
            return True
        if isinstance(result, NotFound):
            if isinstance(state.catalog.resolve(argument), Resolved):
                print(f"{argument} 不在可切换范围：检查 enabled_models。")
            else:
                print(f"没有匹配的可切换模型：{argument}")
            return True
        state.set_model(result.ref.provider, result.ref.model_id)
        print(f"{GLYPH['ok']} Model: {result.ref.display}")
        return True

    return False

def _format_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _show_setting(state: AppState, path: str) -> None:
    key = BY_PATH.get(path)
    if key is None:
        print(f"未知配置键：{path}")
        return
    print(f"{path} = {_format_value(state.settings.get(path))}")
    print(f"  {state.settings.describe(path)}")


def _apply_setting(state: AppState, path: str) -> None:
    """落盘并按生效方式处理：runtime 重建 Agent，restart 提示下次启动。"""
    key = BY_PATH[path]
    if key.apply == APPLY_RUNTIME:
        state.apply_settings()
        print(f"{GLYPH['ok']} {path} = {_format_value(state.settings.get(path))}")
    else:
        save_settings(state.settings)
        print(f"{GLYPH['ok']} {path} = {_format_value(state.settings.get(path))}")
        if key.apply == APPLY_RESTART:
            print("  该配置在下次启动时生效。")


def _set_setting(state: AppState, path: str, raw: str) -> None:
    try:
        state.settings.set(path, raw)
    except ValueError as exc:
        print(f"{GLYPH['fail']} {exc}")
        return
    _apply_setting(state, path)


def _config_menu(state: AppState) -> None:
    group = questionary.select(
        "配置分组", choices=state.settings.groups(), style=UI_STYLE
    ).ask()
    if not group:
        return
    keys = state.settings.keys_of(group)
    choices = [
        questionary.Choice(
            f"{key.short} = {_format_value(state.settings.get(key.path))}", value=key.path
        )
        for key in keys
    ]
    path = questionary.select("修改哪一项", choices=choices, style=UI_STYLE).ask()
    if not path:
        return
    _show_setting(state, path)
    raw = questionary.text(
        "新值（留空取消）", default=_format_value(state.settings.get(path)), style=UI_STYLE
    ).ask()
    if raw is None or not raw.strip():
        return
    _set_setting(state, path, raw.strip())


def _config_command(state: AppState, argument: str) -> None:
    if not argument:
        _config_menu(state)
        return
    parts = argument.split(None, 1)
    path = parts[0]
    if len(parts) == 1:
        _show_setting(state, path)
        return
    _set_setting(state, path, parts[1].strip())


# ---------------------------------------------------------------- /usage

PERIOD_LABELS = {"day": "今天", "week": "本周", "month": "本月"}


def _usage_command(state: AppState, argument: str) -> None:
    """同步账本后按周期展示；同步失败只提示，不挡住已有数据。"""
    period = argument or "day"
    if period not in usage_report.PERIODS:
        print(f"未知统计周期：{period}（可用：day / week / month）")
        return
    try:
        usage_ledger.sync(price=state.catalog.cost)
    except Exception as exc:
        print(f"{GLYPH['fail']} 用量同步失败，仅显示已有记录：{exc}")
    _print_usage(usage_report.report(period))


def _print_usage(data) -> None:
    label = PERIOD_LABELS[data.period]
    span = f"{data.start:%m-%d} ~ {data.end:%m-%d}" if data.period != "day" else f"{data.start:%Y-%m-%d}"
    if not data.rows:
        print(f"{label} {span} · 暂无记录")
        return

    show_cache = any(row.cache_read_tokens for row in data.rows)
    headers = ["渠道", "模型", "输入", "输出"] + (["缓存读"] if show_cache else []) + ["合计", "金额"]
    cells = [
        [row.channel or "未知渠道", row.model, _fmt_tokens(row.input_tokens),
         _fmt_tokens(row.output_tokens)]
        + ([_fmt_tokens(row.cache_read_tokens)] if show_cache else [])
        + [_fmt_tokens(row.tokens), _fmt_money(row.cost)]
        for row in data.rows
    ]
    total = ["合计", "", _fmt_tokens(data.input_tokens), _fmt_tokens(data.output_tokens)] \
        + ([_fmt_tokens(data.cache_read_tokens)] if show_cache else []) \
        + [_fmt_tokens(data.tokens), _fmt_money(data.cost)]

    print()
    print(f"{label} {span} · 用量与花费")
    _table(headers, cells + [total], right_from=2)
    if data.unpriced:
        print(f"  {data.unpriced} 条未定价（渠道未知或缺价），金额不含这些记录。")
    print()


def _table(headers, rows, right_from: int = 0) -> None:
    """对齐的纯文本表：前 `right_from` 列左对齐，其余右对齐；按显示宽度补齐。"""
    widths = [
        max(display_width(row[i]) for row in [headers] + rows)
        for i in range(len(headers))
    ]
    rule = "  " + "  ".join("-" * width for width in widths)
    print("  " + "  ".join(
        pad(cell, widths[i], right=i >= right_from)
        for i, cell in enumerate(headers)
    ))
    print(rule)
    for row in rows:
        print("  " + "  ".join(
            pad(cell, widths[i], right=i >= right_from) for i, cell in enumerate(row)
        ))
    print(rule)


def _fmt_tokens(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}k"
    return str(value)


def _fmt_money(value):
    if value is None:
        return "?"
    if value >= 1:
        return f"${value:.2f}"
    if value >= 0.01:
        return f"${value:.3f}"
    return f"${value:.4f}"
