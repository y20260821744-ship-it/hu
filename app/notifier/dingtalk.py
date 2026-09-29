"""钉钉群机器人（自定义机器人 webhook，支持加签）。"""
from __future__ import annotations

import hashlib
import hmac
import base64
import logging
import time
import urllib.parse

import httpx

from ..config import settings
from .base import Notifier, NotifyMessage

logger = logging.getLogger(__name__)


class DingTalkNotifier(Notifier):
    name = "dingtalk"

    def is_configured(self) -> bool:
        return bool(settings.DINGTALK_WEBHOOK)

    async def send(self, msg: NotifyMessage) -> None:
        url = settings.DINGTALK_WEBHOOK
        if settings.DINGTALK_SECRET:
            timestamp = str(round(time.time() * 1000))
            secret = settings.DINGTALK_SECRET
            string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
            hmac_code = hmac.new(secret.encode("utf-8"), string_to_sign, digestmod=hashlib.sha256).digest()
            sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
            url = f"{url}&timestamp={timestamp}&sign={sign}"

        img_md = f"\n![商品图]({msg.img_url})" if msg.img_url else ""
        markdown_text = (
            f"### 🆕 {msg.platform_name} 上新\n\n"
            f"**{msg.title}**\n\n"
            f"💰 **¥{msg.price_jpy:,}**"
            + (f" (≈￥{msg.price_cny:.0f})" if msg.price_cny else "")
            + f"\n\n👤 卖家: {msg.seller or '-'}\n\n"
            f"📎 [直达链接]({msg.item_url}){img_md}"
        )
        payload = {
            "msgtype": "markdown",
            "markdown": {"title": f"{msg.platform_name}上新: {msg.title[:30]}", "text": markdown_text},
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload)
            data = resp.json()
            if data.get("errcode") not in (0, None):
                raise RuntimeError(f"钉钉发送失败: {data}")
