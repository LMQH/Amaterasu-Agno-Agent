"""斜杠命令、模型名与配置键的补全。"""

from typing import Any, List, Protocol

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import FormattedText

from .ui import COMMANDS, ICONS

# /model 之后的固定参数。
MODEL_ARGUMENTS = [("next", "切换到下一个"), ("prev", "切换到上一个")]


class SettingsLike(Protocol):
    def groups(self) -> List[str]: ...

    def keys_of(self, group: str) -> List[Any]: ...


class SlashCompleter(Completer):
    """补全：/ 开头的命令、/model 后的模型引用，以及 /config 的键。"""

    def __init__(self, models: List[str], settings: SettingsLike) -> None:
        self.models = models
        self.settings = settings

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor

        if text.startswith("/config "):
            prefix = text[len("/config "):]
            for group in self.settings.groups():
                if f"{group}." in prefix and not prefix.endswith("."):
                    continue
                if group.startswith(prefix) and not prefix.endswith("."):
                    yield Completion(f"{group}.", start_position=-len(prefix), display_meta="配置分组")
                for key in self.settings.keys_of(group):
                    path = key.path
                    if path.startswith(prefix):
                        yield Completion(path, start_position=-len(prefix), display_meta=key.label)
            return

        if text.startswith("/model "):
            prefix = text[len("/model "):]
            for value, description in MODEL_ARGUMENTS:
                if value.startswith(prefix):
                    yield Completion(value, start_position=-len(prefix), display_meta=description)
            for model in self.models:
                if model.startswith(prefix):
                    yield Completion(model, start_position=-len(prefix), display_meta="model")
            return

        if text.startswith("/"):
            for command, description in COMMANDS:
                if command.startswith(text):
                    yield Completion(
                        command,
                        start_position=-len(text),
                        display=FormattedText([
                            *([("class:completion-icon", ICONS[command] + " ")] if command in ICONS else []),
                            ("class:completion-command", command),
                        ]),
                        display_meta=description,
                    )
