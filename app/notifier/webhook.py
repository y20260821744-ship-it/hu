"""通用 Webhook 通知：任意 HTTP POST（JSON），便于以后扩展任意渠道。"""
from __future__ import annotations

import logging

import httpx

from ..config import settings
from .base import Notifier, NotifyMessage

logger = logging.getLogger(__name__)


class WebhookNotifier(Notifier):
    name = "webhook"

    def is_configured(self) -> bool:
        return bool(settings.WEBHOOK_URL)

    async def send(self, msg: NotifyMessage) -> None:
        payload = {
            "platform": msg.platform,
            "platform_name": msg.platform_name,
            "item_id": msg.item_id,
            "title": msg.title,
            "price_jpy": msg.price_jpy,
            "price_cny": msg.price_cny,
            "seller": msg.seller,
            "img_url": msg.img_url,
            "item_url": msg.item_url,
            "status": msg.status,
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(settings.WEBHOOK_URL, json=payload)
            if resp.status_code >= 400:
                raise RuntimeError(f"Webhook 发送失败: HTTP {resp.status_code}")
