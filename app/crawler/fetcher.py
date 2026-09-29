"""抓取层：httpx 异步客户端 + 随机 UA + 代理池轮换 + 指数退避 + 失败降频。

代理来源（面板代理池优先，.env 的 PROXY_LIST 兜底）：
- Web 面板「代理池」中维护的启用代理（改完即生效，无需重启）；
- 未配置任何代理时走直连（ALLOW_DIRECT=1）。

合规提示：各平台服务条款禁止高频抓取，请保持最低可用频率；
务必使用日本 IP（原生住宅 IP 最佳），否则大概率被限流/验证码拦截。
"""
from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

import httpx
from sqlalchemy import select

from ..config import settings
from ..database import SessionLocal
from ..models import Proxy, Setting

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# 常见桌面 UA 池，随机轮换降低被识别为爬虫的概率
UA_POOL: List[str] = [
    DEFAULT_UA,
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:126.0) Gecko/20100101 Firefox/126.0",
]


def random_ua() -> str:
    return random.choice(UA_POOL)


# ---------------- 面板代理池（DB 驱动，带版本号缓存） ----------------

_PROXY_POOL_VERSION = 0
_pool_cache: List[str] = []
_pool_cache_ts = 0.0
_pool_loaded_version = -1

_mode_cache: Dict[str, str] = {}
_mode_cache_ts = 0.0

_CACHE_TTL = 30.0  # 秒


def bump_proxy_pool() -> None:
    """面板增删/启停代理后调用，抓取层下次取代理即读到最新列表。"""
    global _PROXY_POOL_VERSION
    _PROXY_POOL_VERSION += 1


def _load_proxy_pool() -> List[str]:
    """合并代理列表：面板启用的代理优先，其次 .env 的 PROXY_LIST。"""
    global _pool_cache, _pool_cache_ts, _pool_loaded_version
    now = time.monotonic()
    if _pool_loaded_version == _PROXY_POOL_VERSION and now - _pool_cache_ts < _CACHE_TTL:
        return _pool_cache

    db_proxies: List[str] = []
    try:
        db = SessionLocal()
        try:
            rows = db.scalars(
                select(Proxy.url).where(Proxy.enabled.is_(True)).order_by(Proxy.id)
            ).all()
            db_proxies = [u.strip() for u in rows if u and u.strip()]
        finally:
            db.close()
    except Exception:  # noqa: BLE001 数据库异常不影响抓取
        db_proxies = []

    _pool_cache = db_proxies + settings.PROXY_LIST
    _pool_cache_ts = now
    _pool_loaded_version = _PROXY_POOL_VERSION
    return _pool_cache


def _get_proxy_mode(platform: str) -> str:
    """读取该平台的代理模式（auto/direct/proxy），30 秒缓存。"""
    global _mode_cache, _mode_cache_ts
    now = time.monotonic()
    if platform in _mode_cache and now - _mode_cache_ts < _CACHE_TTL:
        return _mode_cache[platform]

    mode = "auto"
    try:
        db = SessionLocal()
        try:
            setting = db.get(Setting, platform)
            if setting and setting.proxy_mode:
                mode = setting.proxy_mode
        finally:
            db.close()
    except Exception:  # noqa: BLE001
        pass

    _mode_cache.clear()
    _mode_cache[platform] = mode
    _mode_cache_ts = now
    return mode
