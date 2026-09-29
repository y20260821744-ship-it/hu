"""Server酱 Turbo（微信公众号推送通道）。"""
from __future__ import annotations

import logging

import httpx

from ..config import settings
from .base import Notifier, NotifyMessage

logger = logging.getLogger(__name__)


class ServerChanNotifier(Notifier):
    name = "serverchan"

    def is_configured(self) -> bool:
        return bool(settings.SERVERCHAN_SENDKEY)

    async def send(self, msg: NotifyMessage) -> None:
        payload = {
            "title": f"{msg.platform_name}上新: {msg.title[:30]}",
            "desp": (
                f"### 🆕 {msg.platform_name} 上新\n"
                f"**{msg.title}**\n\n"
                f"💰 ¥{msg.price_jpy:,}"
                + (f" (≈￥{msg.price_cny:.0f})" if msg.price_cny else "")
                + f"\n\n👤 卖家: {msg.seller or '-'}\n\n"
                f"[直达链接]({msg.item_url})"
                + (f"\n\n![商品图]({msg.img_url})" if msg.img_url else "")
            ),
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"https://sctapi.ftqq.com/{settings.SERVERCHAN_SENDKEY}.send",
                data=payload,
            )
            data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(f"Server酱发送失败: {data}")
