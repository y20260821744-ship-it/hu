"""统一商品结构与适配器基类。

每个平台实现为一个 Adapter，输出统一字段：
平台 / 商品ID / 标题 / 价格(日元) / 卖家 / 图片URL / 商品链接 / 上架时间 / 状态
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class PlatformItem:
    platform: str
    item_id: str
    title: str
    price: int = 0  # 日元
    seller: str = ""
    img_url: str = ""
    item_url: str = ""
    listed_at: Optional[datetime] = None
    status: str = "在售"  # 在售 / 售出 / 竞拍中
    raw: dict = field(default_factory=dict)  # 平台原始数据（调试用）

    def unique_key(self) -> str:
        return f"{self.platform}:{self.item_id}"

    def __repr__(self) -> str:  # pragma: no cover
        return f"<{self.unique_key()} ¥{self.price} {self.title[:24]}>"


class Adapter(ABC):
    """平台适配器基类。"""

    platform: str = ""  # 适配器注册名（数据库中的平台标识）
    display_name: str = ""  # 面板展示名
    base_url: str = ""
    search_url_template: str = ""  # 需包含 {keyword} 占位符（URL 编码后）

    @abstractmethod
    async def search(self, keyword: str) -> List[PlatformItem]:
        """按关键词搜索，返回归一化商品列表。"""

    def build_search_url(self, keyword: str) -> str:
        from urllib.parse import quote

        return self.search_url_template.format(keyword=quote(keyword))

    @staticmethod
    def _clean_text(text: str) -> str:
        """清理标题/文本中的空白与换行。"""
        import re

        text = re.sub(r"<[^>]+>", "", text)
        text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        text = re.sub(r"\s+", " ", text).strip()
        return text

    @staticmethod
    def _parse_price(text: str) -> int:
        """把 '¥1,234' / '1,234円' / '1,234' 解析为 int 日元。"""
        import re

        digits = re.sub(r"[^\d]", "", text or "")
        try:
            return int(digits) if digits else 0
        except ValueError:
            return 0
