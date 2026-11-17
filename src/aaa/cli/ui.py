"""终端表现：命令表、符号、样式、状态条与光标。"""

import os
import sys
import unicodedata

import questionary
from prompt_toolkit.styles import Style as PromptStyle

# 配置向导与菜单的样式：只加粗关键位置，不使用主题色。
UI_STYLE = questionary.Style([
    ("qmark", "bold"),
    ("pointer", "bold"),
    ("highlighted", "bold"),
    ("selected", "bold"),
])

COMMANDS = [
    ("/help", "显示所有命令"),
    ("/config", "查看或修改配置（可省略参数进入菜单）"),
    ("/provide", "编辑渠道与模型"),
    ("/model", "切换模型（<渠道>/<模型>、next、prev）"),
    ("/mode", "切换权限模式（read-only / workspace-write / danger-full-access）"),
    ("/compact", "立即压缩当前会话上下文"),
    ("/usage", "查看用量与花费（默认今天，可跟 week / month）"),
    ("/session", "列出或切换历史会话"),
    ("/new", "新建会话"),
    ("/exit", "退出"),
]

# 符号表：Windows 控制台默认字体缺字较多，直接退回 ASCII；
# macOS/Linux 使用最简线条符号，不依赖 Nerd Font。
ASCII_UI = os.name == "nt"
GLYPH = {
    "prompt": ">" if ASCII_UI else "❯",
    "ok": "+" if ASCII_UI else "✔",
    "fail": "x" if ASCII_UI else "✘",
    "dot": "-" if ASCII_UI else "·",
    "working": "~" if ASCII_UI else "⎋",
    "bar": "-" if ASCII_UI else "─",
    "mark": "|===|" if ASCII_UI else "╎───┃",
    "title": ">" if ASCII_UI else "▸",
}

# 命令图标：Windows 不显示图标，其余平台用最简符号。
ICONS = {} if ASCII_UI else {
    "/help": "?",
    "/config": "≡",
    "/provide": "⚙",
    "/model": "◆",
    "/mode": "▣",
    "/compact": "⇩",
    "/usage": "Σ",
    "/session": "▤",
    "/new": "+",
    "/exit": "x",
}

# 输入区与补全菜单的样式：深色菜单、青色提示符，其余保持低对比。
PT_STYLE = PromptStyle.from_dict({
    "prompt": "ansicyan bold",
    "toolbar": "bg:#1e1e1e #999999",
    "toolbar.model": "bg:#1e1e1e #dddddd",
    "toolbar.dim": "bg:#1e1e1e #777777",
    "completion-menu.completion": "bg:#1e1e1e #cccccc",
    "completion-menu.completion.current": "bg:#333333 #ffffff",
    "completion-menu.meta.completion": "bg:#1e1e1e #888888",
    "completion-menu.meta.completion.current": "bg:#333333 #dddddd",
    "completion-icon": "#7fd1ff",
    "completion-command": "#ffffff",
})


def display_width(text: str) -> int:
    """终端显示宽度：中日韩全角字符占两列。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def pad(text: str, width: int, right: bool = False) -> str:
    """按显示宽度补齐；`right` 为真时右对齐。"""
    gap = max(0, width - display_width(text))
    return " " * gap + text if right else text + " " * gap


def print_help() -> None:
    print()
    for command, description in COMMANDS:
        print(f"  {command:<10}{description}")
    print()


def fmt_window(value: int) -> str:
    """把上下文窗口压成 128k / 1M。"""
    if value >= 1_000_000:
        return f"{value / 1_000_000:.0f}M"
    if value >= 1_000:
        return f"{value / 1_000:.0f}k"
    return str(value)


def context_bar(used: int, total: int, width: int, compact_at: int = 0) -> str:
    """omp 风格：百分比在进度位置，压缩阈值处带预留标记，右端是窗口上限。"""
    width = max(24, width)
    ratio = min(used / total, 1.0) if total else 0.0
    label = f"{ratio * 100:.0f}%"
    marker = GLYPH["mark"]
    room = max(width - len(marker), len(label) + 2)
    chars = [GLYPH["bar"]] * room

    if compact_at and total:
        mpos = min(int(min(compact_at / total, 1.0) * room), room - len(marker))
    else:
        mpos = room - len(marker)
    mpos = max(mpos, len(label) + 1)
    chars[mpos:mpos + len(marker)] = list(marker)

    pos = min(int(ratio * room), room - len(label))
    if pos > mpos - len(label) - 1:
        pos = max(0, mpos - len(label) - 1)
    chars[pos:pos + len(label)] = list(label)

    return "".join(chars) + " " + fmt_window(total)


class StatusLine:
    """单行状态：用 \\r 原地刷新；输出正文前必须先 clear，避免交错。"""

    def __init__(self) -> None:
        self._text = ""

    def _write(self, text: str) -> None:
        if not sys.stdout.isatty():
            return
        sys.stdout.write("\r\x1b[K" + text)
        sys.stdout.flush()

    def update(self, text: str) -> None:
        if text == self._text:
            return
        self._text = text
        self._write(text)

    def clear(self) -> None:
        if self._text:
            self._text = ""
            self._write("")


def set_cursor_color(color: str) -> None:
    """用 OSC 12 设置光标颜色；不支持的终端会静默忽略。"""
    if sys.stdout.isatty():
        sys.stdout.write(f"\x1b]12;{color}\x07")
        sys.stdout.flush()


def reset_cursor_color() -> None:
    """恢复终端默认光标颜色（OSC 112）。"""
    if sys.stdout.isatty():
        sys.stdout.write("\x1b]112\x07")
        sys.stdout.flush()
