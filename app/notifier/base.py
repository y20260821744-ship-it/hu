"""通知渠道抽象：统一 Notifier 接口 + 消息结构。

渠道可插拔、可多路同时推送；推送失败由 Manager 自动重试 3 次并记录日志。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class NotifyMessage:
    """一次上新通知的完整内容（渠道无关）。"""

    platform: str  # mercari / suruga
    platform_name: str  # 展示名
    item_id: str
    title: str
    price_jpy: int
    price_cny: Optional[float] = None  # 人民币换算（可选）
    seller: str = ""
    img_url: str = ""
    item_url: str = ""
    status: str = "在售"

    def caption(self, with_cny: bool = True) -> str:
        """生成通用文本（各渠道在此基础上微调）。"""
        lines = [
            f"🆕 {self.platform_name} 上新",
            f"📦 {self.title}",
            f"💰 ¥{self.price_jpy:,}",
        ]
        if with_cny and self.price_cny:
            lines.append(f"   ≈ ￥{self.price_cny:.0f}")
        if self.seller:
            lines.append(f"👤 卖家: {self.seller}")
        lines.append(f"📎 {self.item_url}")
        return "\n".join(lines)


class Notifier(ABC):
    """渠道基类。name 用于配置与日志标识。"""

    name: str = ""

    @abstractmethod
    async def send(self, msg: NotifyMessage) -> None:
        """发送；失败抛异常，由 Manager 决定重试。"""

    def is_configured(self) -> bool:
        """该渠道是否已配置（默认 True，子类可覆盖检查必需配置项）。"""
        return True
