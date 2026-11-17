"""REPL 的可变状态。每个事实只有一个写入点。"""

from dataclasses import dataclass, field
from typing import Dict, Optional, Set, Tuple

from agno.agent import Agent

from ..config.loader import save_config
from ..config.settings import Settings, save
from ..model.catalog import Catalog, ModelRef, from_config
from ..model.provider import Channel, ChannelModel
from ..runtime.agent import build_agent
from ..sessions.query import new_session_id
from .completer import SlashCompleter


@dataclass
class AppState:
    """一次进程内的全部可变状态：配置、渠道、模型、权限模式、会话与 agent。"""

    config: Dict
    settings: Settings
    catalog: Catalog
    provider: str
    model_id: str
    mode: str
    agent: Agent
    session_id: str
    completer: SlashCompleter
    context_tokens: Optional[int] = None
    # 本会话内已批准的工具调用签名（工具名 + 参数）；同一命令不再重复询问。
    approved: Set[str] = field(default_factory=set)

    @classmethod
    def start(cls, config: Dict, settings: Settings) -> "AppState":
        """按归一后的配置构造初始状态，含首次 agent 装配。"""
        catalog = from_config(config, settings)
        default = config["default"]
        provider, model_id = default["provider"], default["model"]
        mode = settings.get("boundary.default_mode")
        scope = catalog.scope(config.get("enabled_models") or [])
        return cls(
            config=config,
            settings=settings,
            catalog=catalog,
            provider=provider,
            model_id=model_id,
            mode=mode,
            agent=build_agent(catalog, provider, model_id, mode, settings),
            session_id=new_session_id(settings),
            completer=SlashCompleter([ref.display for ref in scope], settings),
        )

    @property
    def model_ref(self) -> ModelRef:
        return ModelRef(self.provider, self.model_id)

    def selection(self) -> Tuple[Channel, ChannelModel]:
        """当前渠道与模型；一次查询，供标题生成等无状态调用使用。"""
        return self.catalog.require(self.provider, self.model_id)

    def window(self) -> int:
        """当前模型的上下文窗口；不缓存，避免与配置分叉。"""
        return self.catalog.window(self.provider, self.model_id)

    def rebuild_agent(self) -> None:
        """按当前渠道、模型、权限模式与配置重建 agent，并丢弃上一轮的 token 统计。"""
        self.agent = build_agent(
            self.catalog, self.provider, self.model_id, self.mode, self.settings
        )
        self.completer = SlashCompleter([ref.display for ref in self.scope()], self.settings)
        self.context_tokens = None

    def scope(self) -> Tuple[ModelRef, ...]:
        """可切换范围：enabled_models 模式匹配后的模型。"""
        return self.catalog.scope(self.config.get("enabled_models") or [])

    def set_model(self, provider: str, model_id: str, *, persist: bool = True) -> None:
        """切换模型：先确认存在，再重建，最后才落盘。"""
        self.catalog.require(provider, model_id)
        self.provider, self.model_id = provider, model_id
        self.rebuild_agent()
        if persist:
            self.config["default"] = {"provider": provider, "model": model_id}
            save_config(self.config)

    def cycle_model(self, step: int) -> Optional[ModelRef]:
        """在可切换范围里前后移动；范围不足两个时返回 None。"""
        refs = list(self.scope())
        if len(refs) < 2:
            return None
        try:
            index = refs.index(self.model_ref)
        except ValueError:
            index = 0
        return refs[(index + step) % len(refs)]

    def apply_config(self, config: Dict) -> None:
        """渠道编辑后换掉配置与目录，回到新的默认模型。"""
        self.config = config
        self.catalog = from_config(config, self.settings)
        default = config["default"]
        self.set_model(default["provider"], default["model"], persist=False)

    def apply_settings(self) -> None:
        """配置改完：先落盘，再按生效方式重建。"""
        save(self.settings)
        self.catalog = from_config(self.config, self.settings)
        self.rebuild_agent()
