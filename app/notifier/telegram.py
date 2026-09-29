"""Telegram Bot 通知（推荐主通道：稳定、免费）。"""
from __future__ import annotations

import logging

import httpx

from ..config import settings
from .base import Notifier, NotifyMessage

logger = logging.getLogger(__name__)


class TelegramNotifier(Notifier):
    name = "telegram"

    def is_configured(self) -> bool:
        return bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID)

    async def send(self, msg: NotifyMessage) -> None:
        token = settings.TELEGRAM_BOT_TOKEN
        chat_id = settings.TELEGRAM_CHAT_ID
        api = f"https://api.telegram.org/bot{token}"
        text = msg.caption()

        # 优先带图发送（sendPhoto），失败退回纯文本
        async with httpx.AsyncClient(timeout=15) as client:
            if msg.img_url:
                resp = await client.post(
                    f"{api}/sendPhoto",
                    json={
                        "chat_id": chat_id,
                        "photo": msg.img_url,
                        "caption": text,
                    },
                )
                data = resp.json()
                if data.get("ok"):
                    return
                logger.warning("Telegram sendPhoto 失败: %s，回退纯文本", data.get("description"))

            resp = await client.post(
                f"{api}/sendMessage",
                json={"chat_id": chat_id, "text": text, "disable_web_page_preview": False},
            )
            data = resp.json()
            if not data.get("ok"):
                raise RuntimeError(f"Telegram sendMessage 失败: {data.get('description')}")
