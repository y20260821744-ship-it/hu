"""邮件 SMTP 通知。"""
from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from ..config import settings
from .base import Notifier, NotifyMessage

logger = logging.getLogger(__name__)


class EmailNotifier(Notifier):
    name = "email"

    def is_configured(self) -> bool:
        return bool(settings.SMTP_HOST and settings.SMTP_USER and settings.SMTP_TO)

    async def send(self, msg: NotifyMessage) -> None:
        # smtplib 为阻塞实现，放入线程池执行避免阻塞事件循环
        import asyncio

        await asyncio.to_thread(self._send_sync, msg)

    def _send_sync(self, msg: NotifyMessage) -> None:
        body = (
            f"<h3>🆕 {msg.platform_name} 上新</h3>"
            f"<p><b>{msg.title}</b></p>"
            f"<p>💰 ¥{msg.price_jpy:,}"
            + (f" (≈￥{msg.price_cny:.0f})" if msg.price_cny else "")
            + f"</p>"
            f"<p>👤 卖家: {msg.seller or '-'}</p>"
            f'<p><a href="{msg.item_url}">直达链接</a></p>'
            + (f'<p><img src="{msg.img_url}" style="max-width:100%%"/></p>' if msg.img_url else "")
        )
        mime = MIMEMultipart("alternative")
        mime["Subject"] = f"{msg.platform_name}上新: {msg.title[:40]}"
        mime["From"] = settings.SMTP_FROM or settings.SMTP_USER
        mime["To"] = settings.SMTP_TO
        mime.attach(MIMEText(body, "html", "utf-8"))

        context = None
        if settings.SMTP_PORT == 465:
            import ssl

            context = ssl.create_default_context()
        with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, context=context) as server:
            if settings.SMTP_USER:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD or "")
            server.sendmail(mime["From"], [settings.SMTP_TO], mime.as_string())
