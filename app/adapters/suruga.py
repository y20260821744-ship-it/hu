"""骏河屋（Suruga-ya JP）适配器。

抓取形态：商品检索页 SSR HTML，卡片解析。
主要品类：中古游戏 / 玩具 / 周边 / 卡牌等。
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import List, Optional

from bs4 import BeautifulSoup

from ..crawler.fetcher import Fetcher
from .base import Adapter, PlatformItem

# 商品详情链接形如 https://www.suruga-ya.jp/product/detail/226016123
_ITEM_URL_RE = re.compile(r"/product/detail/(\d{6,})")


class SurugaAdapter(Adapter):
    platform = "suruga"
    display_name = "骏河屋 Suruga-ya"
    base_url = "https://www.suruga-ya.jp"
    search_url_template = "https://www.suruga-ya.jp/search?search_word={keyword}&category="

    def __init__(self, fetcher: Optional[Fetcher] = None) -> None:
        self.fetcher = fetcher or Fetcher()

    async def search(self, keyword: str) -> List[PlatformItem]:
        url = self.build_search_url(keyword)
        html = await self.fetcher.fetch(url, self.platform, referer=self.base_url)
        return self._parse_html(html)

    def _parse_html(self, html: str) -> List[PlatformItem]:
        soup = BeautifulSoup(html, "html.parser")
        items: List[PlatformItem] = []
        seen: set[str] = set()

        # 遍历所有包含商品详情链接的 <a>
        for a in soup.find_all("a", href=_ITEM_URL_RE):
            href = a.get("href", "")
            m = _ITEM_URL_RE.search(href)
            if not m:
                continue
            code = m.group(1)
            if code in seen:
                continue
            seen.add(code)

            # 标题：多数卡片在 <strong> 内（关键词会加 <em>/<strong> 高亮）
            title_node = a.find("strong") or a
            title = self._clean_text(title_node.get_text(" ", strip=True) or "")
            if not title:
                # 尝试向上找商品块
                block = a.find_parent(class_=re.compile(r"product|item|list"))
                if block:
                    title = self._clean_text(block.get_text(" ", strip=True)[:200])
            if not title:
                title = f"Suruga-ya {code}"

            price = 0
            block = a.find_parent(class_=re.compile(r"product|item|list")) or a
            price_node = block.find(class_=re.compile(r"price|sell_price|red"))
            if price_node:
                price = self._parse_price(price_node.get_text())

            img_url = ""
            img = block.find("img")
            if img:
                img_url = img.get("src") or img.get("data-src") or img.get("lazy-src") or ""

            seller = "駿河屋"

            # 售罄判断：常见标识 "sold out" / "売切"
            status = "在售"
            if block and re.search(r"sold\s*out|売切|完売", block.get_text(" ", strip=True), re.I):
                status = "售出"

            items.append(
                PlatformItem(
                    platform=self.platform,
                    item_id=code,
                    title=title,
                    price=price,
                    seller=seller,
                    img_url=img_url,
                    item_url=f"{self.base_url}/product/detail/{code}",
                    listed_at=None,
                    status=status,
                )
            )
        return items
