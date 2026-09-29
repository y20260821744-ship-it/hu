"""企业微信群机器人 webhook 通知（微信内可直接收到，稳定免费）。

注意：个人微信自动化（wxauto/wechaty 等）存在封号风险，本项目默认不实现，
仅保留 Notifier 接口，需要时可按同一模式扩展。
"""
from __future__ import annotations

import logging

import httpx

from ..config import settings
from .base import Notifier, NotifyMessage

logger = logging.getLogger(__name__)


class WeComNotifier(Notifier):
    name = "wecom"

    def is_configured(self) -> bool:
        return bool(settings.WECOM_WEBHOOK)

    async def send(self, msg: NotifyMessage) -> None:
        img_md = f"\n![商品图]({msg.img_url})" if msg.img_url else ""
        markdown_text = (
            f"### 🆕 {msg.platform_name} 上新\n"
            f"**{msg.title}**\n"
            f"> 💰 ¥{msg.price_jpy:,}"
            + (f" (≈￥{msg.price_cny:.0f})" if msg.price_cny else "")
            + f"\n> 👤 卖家: {msg.seller or '-'}\n"
            f"> [直达链接]({msg.item_url}){img_md}"
        )
        payload = {"msgtype": "markdown", "markdown": {"content": markdown_text}}
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(settings.WECOM_WEBHOOK, json=payload)
            data = resp.json()
            if data.get("errcode") != 0:
                raise RuntimeError(f"企业微信发送失败: {data}")
