"""PushPlus（微信公众号推送通道，第三方，免认证服务号）。"""
from __future__ import annotations

import logging

import httpx

from ..config import settings
from .base import Notifier, NotifyMessage

logger = logging.getLogger(__name__)


class PushPlusNotifier(Notifier):
    name = "pushplus"

    def is_configured(self) -> bool:
        return bool(settings.PUSHPLUS_TOKEN)

    async def send(self, msg: NotifyMessage) -> None:
        img_html = f'<br/><img src="{msg.img_url}" style="max-width:100%%"/>' if msg.img_url else ""
        html = (
            f"<h3>🆕 {msg.platform_name} 上新</h3>"
            f"<p><b>{msg.title}</b></p>"
            f"<p>💰 ¥{msg.price_jpy:,}"
            + (f" (≈￥{msg.price_cny:.0f})" if msg.price_cny else "")
            + f"</p>"
            f"<p>👤 卖家: {msg.seller or '-'}</p>"
            f'<p><a href="{msg.item_url}">直达链接</a></p>{img_html}'
        )
        payload = {
            "token": settings.PUSHPLUS_TOKEN,
            "title": f"{msg.platform_name}上新: {msg.title[:30]}",
            "content": html,
            "template": "html",
        }
        if settings.PUSHPLUS_TOPIC:
            payload["topic"] = settings.PUSHPLUS_TOPIC
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post("https://www.pushplus.plus/send", json=payload)
            data = resp.json()
            if data.get("code") != 200:
                raise RuntimeError(f"PushPlus 发送失败: {data.get('msg')}")
