"""Bark (iOS) 通知：URL scheme，GET 请求即可。"""
from __future__ import annotations

import logging
import urllib.parse

import httpx

from ..config import settings
from .base import Notifier, NotifyMessage

logger = logging.getLogger(__name__)


class BarkNotifier(Notifier):
    name = "bark"

    def is_configured(self) -> bool:
        return bool(settings.BARK_KEY)

    async def send(self, msg: NotifyMessage) -> None:
        server = settings.BARK_SERVER.rstrip("/")
        title = f"{msg.platform_name}上新 ¥{msg.price_jpy:,}"
        body = f"{msg.title}\n卖家: {msg.seller or '-'}\n{msg.item_url}"

        url = f"{server}/{settings.BARK_KEY}/{urllib.parse.quote(title)}/{urllib.parse.quote(body)}"
        params = {}
        if msg.img_url:
            params["icon"] = msg.img_url
            params["url"] = msg.item_url
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                raise RuntimeError(f"Bark 发送失败: HTTP {resp.status_code}")
