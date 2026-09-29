"""平台适配器包。"""
from .base import Adapter, PlatformItem
from .registry import all_adapters, get_adapter, init_adapters, supported_platforms

__all__ = [
    "Adapter",
    "PlatformItem",
    "init_adapters",
    "get_adapter",
    "all_adapters",
    "supported_platforms",
]
