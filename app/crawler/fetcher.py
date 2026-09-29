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


@dataclass
class PlatformThrottle:
    """单平台风控状态：连续失败计数 + 当前退避 + 降频标记。"""

    consecutive_failures: int = 0
    backoff_seconds: float = 0.0
    downgraded: bool = False  # 已自动降频（面板会显示告警）

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.backoff_seconds = 0.0

    def record_failure(self) -> float:
        """记录一次失败，返回下次请求前需要等待的秒数（指数退避）。"""
        self.consecutive_failures += 1
        base = settings.RETRY_BASE_BACKOFF
        self.backoff_seconds = min(base * (2 ** (self.consecutive_failures - 1)), 300)
        if self.consecutive_failures >= settings.FAILURE_DOWNGRADE_THRESHOLD:
            self.downgraded = True
        return self.backoff_seconds


class Fetcher:
    """负责 GET 文本抓取：代理轮换、UA 轮换、超时、重试 + 指数退避。"""

    def __init__(self) -> None:
        self._proxy_round_robin = 0
        self._throttles: Dict[str, PlatformThrottle] = {}

    def throttle_for(self, platform: str) -> PlatformThrottle:
        if platform not in self._throttles:
            self._throttles[platform] = PlatformThrottle()
        return self._throttles[platform]

    def _next_proxy(self, platform: str) -> Optional[str]:
        """取下一个代理（轮换）。direct 模式或池为空时返回 None（直连）。"""
        if _get_proxy_mode(platform) == "direct":
            return None
        pool = _load_proxy_pool()
        if not pool:
            return None
        proxy = pool[self._proxy_round_robin % len(pool)]
        self._proxy_round_robin += 1
        return proxy

    def _build_client(self, platform: str) -> httpx.AsyncClient:
        proxy = self._next_proxy(platform)
        return httpx.AsyncClient(
            headers={
                "User-Agent": random_ua(),
                "Accept-Language": "ja,zh-CN;q=0.9,en;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            },
            timeout=httpx.Timeout(settings.REQUEST_TIMEOUT),
            proxy=proxy if proxy else None,
            follow_redirects=True,
            http2=False,
        )

    async def fetch(self, url: str, platform: str, referer: str = "") -> str:
        """抓取页面文本。失败时按指数退避重试；连续失败触发降频标记。

        返回 HTML 文本；全部失败抛 RuntimeError。
        """
        throttle = self.throttle_for(platform)

        # 退避等待
        if throttle.backoff_seconds > 0:
            await asyncio.sleep(min(throttle.backoff_seconds, 10))

        last_error: Optional[Exception] = None
        for attempt in range(1, settings.MAX_RETRIES + 1):
            client = self._build_client(platform)
            try:
                if referer:
                    client.headers["Referer"] = referer
                resp = await client.get(url)
                if resp.status_code == 200:
                    throttle.record_success()
                    return resp.text
                if resp.status_code in (403, 429) or resp.status_code >= 500:
                    # 验证码 / 限流 / 服务端错误：视为需要退避
                    throttle.record_failure()
                    last_error = RuntimeError(f"HTTP {resp.status_code}")
                else:
                    last_error = RuntimeError(f"HTTP {resp.status_code}")
            except Exception as exc:  # noqa: BLE001 网络异常统一处理
                throttle.record_failure()
                last_error = exc
            finally:
                await client.aclose()

            if attempt < settings.MAX_RETRIES:
                await asyncio.sleep(min(settings.RETRY_BASE_BACKOFF * attempt, 10))

        raise RuntimeError(f"抓取失败 [{platform}] {url}: {last_error}")
