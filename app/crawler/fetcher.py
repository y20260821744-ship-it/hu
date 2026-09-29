"""抓取层：httpx 异步客户端 + 随机 UA + 代理池轮换 + 指数退避 + 失败降频。

合规提示：各平台服务条款禁止高频抓取，请保持最低可用频率；
国内 IP 大概率被限流/验证码拦截，务必配置日本 IP 代理池。
"""
from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import httpx

from ..config import settings

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


def _pick_proxy(index: int) -> Optional[str]:
    proxies = settings.PROXY_LIST
    if not proxies:
        return None
    return proxies[index % len(proxies)]


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

    def _next_proxy(self) -> Optional[str]:
        if not settings.PROXY_LIST:
            return None
        proxy = _pick_proxy(self._proxy_round_robin)
        self._proxy_round_robin += 1
        return proxy

    def _build_client(self) -> httpx.AsyncClient:
        proxy = self._next_proxy()
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
            client = self._build_client()
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
