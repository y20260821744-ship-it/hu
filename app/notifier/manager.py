"""通知管理器：多渠道并行发送、失败自动重试 3 次、写推送日志。"""
from __future__ import annotations

import asyncio
import logging
from typing import Dict, List

from ..config import settings
from ..models import PushLog
from .base import Notifier, NotifyMessage
from .bark import BarkNotifier
from .dingtalk import DingTalkNotifier
from .email import EmailNotifier
from .pushplus import PushPlusNotifier
from .serverchan import ServerChanNotifier
from .telegram import TelegramNotifier
from .webhook import WebhookNotifier
from .wecom import WeComNotifier
from .wxpusher import WxPusherNotifier

logger = logging.getLogger(__name__)

# 所有渠道注册表
ALL_NOTIFIERS: Dict[str, Notifier] = {
    n.name: n
    for n in [
        TelegramNotifier(),
        DingTalkNotifier(),
        BarkNotifier(),
        WeComNotifier(),
        PushPlusNotifier(),
        WxPusherNotifier(),
        ServerChanNotifier(),
        EmailNotifier(),
        WebhookNotifier(),
    ]
}


class NotifierManager:
    """负责把一个 NotifyMessage 发往多个渠道。

    - 渠道列表来自平台设置（DB settings.channels），未设置时用配置默认值；
    - 单渠道失败自动重试 3 次（指数退避），最终失败写入 PushLog 便于面板展示。
    """

    RETRY_TIMES = 3

    def enabled_notifiers(self, channel_names: List[str]) -> List[Notifier]:
        result = []
        for name in channel_names:
            notifier = ALL_NOTIFIERS.get(name)
            if notifier and notifier.is_configured():
                result.append(notifier)
        return result

    async def notify(
        self,
        msg: NotifyMessage,
        channel_names: List[str],
        db_item_id: int,
        db,
    ) -> Dict[str, str]:
        """发送到指定渠道列表。返回 {channel: 'success'|'failed'}。"""
        notifiers = self.enabled_notifiers(channel_names)
        if not notifiers:
            logger.info("没有已配置的启用渠道，跳过推送 (item=%s)", db_item_id)
            return {}

        results: Dict[str, str] = {}
        for notifier in notifiers:
            status, error = await self._send_with_retry(notifier, msg)
            results[notifier.name] = status
            log = PushLog(
                item_id=db_item_id,
                channel=notifier.name,
                status=status,
                error=error,
                retry_count=self.RETRY_TIMES if status == "failed" else 0,
            )
            db.add(log)
        db.commit()
        return results

    async def _send_with_retry(self, notifier: Notifier, msg: NotifyMessage) -> tuple[str, str]:
        last_error = ""
        for attempt in range(1, self.RETRY_TIMES + 1):
            try:
                await notifier.send(msg)
                logger.info("推送成功: %s -> %s", notifier.name, msg.item_id)
                return "success", ""
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                logger.warning("推送失败[%s] 第%d次: %s", notifier.name, attempt, exc)
                if attempt < self.RETRY_TIMES:
                    await asyncio.sleep(min(2 * attempt, 10))
        return "failed", last_error[:500]
