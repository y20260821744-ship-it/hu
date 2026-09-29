"""WxPusher（微信公众号推送通道，第三方）。"""
from __future__ import annotations

import logging

import httpx

from ..config import settings
from .base import Notifier, NotifyMessage

logger = logging.getLogger(__name__)


class WxPusherNotifier(Notifier):
    name = "wxpusher"

    def is_configured(self) -> bool:
        return bool(settings.WXPUSHER_APP_TOKEN)

    async def send(self, msg: NotifyMessage) -> None:
        content = (
            f"🆕 {msg.platform_name} 上新\n"
            f"📦 {msg.title}\n"
            f"💰 ¥{msg.price_jpy:,}"
            + (f" (≈￥{msg.price_cny:.0f})" if msg.price_cny else "")
            + f"\n👤 卖家: {msg.seller or '-'}\n"
            f"🔗 {msg.item_url}"
        )
        payload = {
            "appToken": settings.WXPUSHER_APP_TOKEN,
            "content": content,
            "summary": f"{msg.platform_name}上新: {msg.title[:20]}",
            "contentType": 1,
        }
        if msg.img_url:
            payload["url"] = msg.img_url
        if settings.WXPUSHER_TOPIC_ID:
            payload["topicIds"] = [int(x) for x in settings.WXPUSHER_TOPIC_ID.split(",") if x.strip()]
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post("https://wxpusher.zjiecode.com/api/send/message", json=payload)
            data = resp.json()
            if data.get("code") != 1000:
                raise RuntimeError(f"WxPusher 发送失败: {data}")
