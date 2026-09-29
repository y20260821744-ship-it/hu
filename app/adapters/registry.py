"""适配器注册表：新增平台只需新增 Adapter 并在此注册，无需改动核心逻辑。"""
from __future__ import annotations

from typing import Dict, List

from ..crawler.fetcher import Fetcher
from .base import Adapter
from .mercari import MercariAdapter
from .suruga import SurugaAdapter

_adapters: Dict[str, Adapter] = {}


def register(adapter: Adapter) -> None:
    _adapters[adapter.platform] = adapter


def get_adapter(platform: str) -> Adapter:
    if not _adapters:
        init_adapters()
    if platform not in _adapters:
        raise KeyError(f"未注册的平台适配器: {platform}")
    return _adapters[platform]


def all_adapters() -> List[Adapter]:
    if not _adapters:
        init_adapters()
    return list(_adapters.values())


def supported_platforms() -> List[str]:
    return [a.platform for a in all_adapters()]


def init_adapters(fetcher: Fetcher | None = None) -> None:
    """初始化全部适配器（共享同一个 Fetcher，便于统一风控状态）。"""
    global _adapters
    f = fetcher or Fetcher()
    _adapters = {
        "mercari": MercariAdapter(f),
        "suruga": SurugaAdapter(f),
    }
