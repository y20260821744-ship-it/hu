"""煤炉（Mercari JP）适配器。

抓取形态：搜索页 SSR HTML，优先解析 __NEXT_DATA__ JSON（Next.js 服务端注入），
兜底用正则匹配商品卡片链接。

注意：Mercari 对高频访问与数据中心 IP 有限制，请配置日本 IP 代理并保持低频。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, List, Optional

from bs4 import BeautifulSoup

from ..crawler.fetcher import Fetcher
from .base import Adapter, PlatformItem

# 商品卡片链接形如 /jp/items/m1234567890123
_ITEM_URL_RE = re.compile(r"/jp/items/(m\d{8,})")


class MercariAdapter(Adapter):
    platform = "mercari"
    display_name = "煤炉 Mercari"
    base_url = "https://jp.mercari.com"
    search_url_template = "https://jp.mercari.com/search?keyword={keyword}"

    def __init__(self, fetcher: Optional[Fetcher] = None) -> None:
        self.fetcher = fetcher or Fetcher()

    async def search(self, keyword: str) -> List[PlatformItem]:
        url = self.build_search_url(keyword)
        html = await self.fetcher.fetch(url, self.platform, referer=self.base_url)

        items: List[PlatformItem] = []
        # 策略 1：__NEXT_DATA__
        items = self._parse_next_data(html)
        if items:
            return items
        # 策略 2：HTML 卡片正则兜底
        items = self._parse_html_fallback(html)
        return items

    # ---------------- 解析 ----------------

    def _parse_next_data(self, html: str) -> List[PlatformItem]:
        """递归提取 __NEXT_DATA__ 中的商品列表。"""
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
        if not m:
            return []
        try:
            payload = json.loads(m.group(1))
        except json.JSONDecodeError:
            return []

        results: List[PlatformItem] = []
        seen: set[str] = set()

        def walk(node: Any) -> None:
            if not isinstance(node, dict):
                return
            # 找形如 {"items": [ {...item...}, ... ]} 的节点
            for key, value in node.items():
                if key == "items" and isinstance(value, list) and value:
                    for it in value:
                        if isinstance(it, dict) and it.get("id"):
                            item = self._from_raw_item(it)
                            if item and item.unique_key() not in seen:
                                seen.add(item.unique_key())
                                results.append(item)
                elif isinstance(value, (dict, list)):
                    if isinstance(value, dict):
                        walk(value)
                    else:
                        for sub in value:
                            if isinstance(sub, (dict, list)):
                                walk(sub)

        walk(payload)
        return results

    def _from_raw_item(self, raw: dict) -> Optional[PlatformItem]:
        item_id = str(raw.get("id") or raw.get("itemId") or "")
        if not item_id.startswith("m"):
            item_id = "m" + item_id
        title = self._clean_text(str(raw.get("name") or raw.get("title") or ""))
        if not title:
            return None

        price = 0
        price_raw = raw.get("price")
        if isinstance(price_raw, dict):
            price = self._parse_price(str(price_raw.get("amount") or ""))
        elif price_raw is not None:
            price = self._parse_price(str(price_raw))

        status = "在售"
        if raw.get("status") in ("sold_out", "sold") or raw.get("itemStatus") == "sold_out":
            status = "售出"

        listed_at: Optional[datetime] = None
        created = raw.get("created") or raw.get("createdAt")
        if created:
            listed_at = self._parse_dt(created)

        seller = ""
        seller_node = raw.get("seller")
        if isinstance(seller_node, dict):
            seller = str(seller_node.get("name") or seller_node.get("sellerId") or "")

        img_url = ""
        photos = raw.get("photos") or raw.get("thumbnails") or []
        if photos and isinstance(photos, list):
            first = photos[0]
            if isinstance(first, dict):
                img_url = str(first.get("url") or "")
            else:
                img_url = str(first)

        return PlatformItem(
            platform=self.platform,
            item_id=item_id,
            title=title,
            price=price,
            seller=seller,
            img_url=img_url,
            item_url=f"{self.base_url}/jp/items/{item_id}",
            listed_at=listed_at,
            status=status,
            raw=raw,
        )

    def _parse_html_fallback(self, html: str) -> List[PlatformItem]:
        """正则兜底：抓卡片链接 + 邻近标题/价格。"""
        soup = BeautifulSoup(html, "html.parser")
        items: List[PlatformItem] = []
        seen: set[str] = set()

        anchors = soup.find_all("a", href=_ITEM_URL_RE)
        for a in anchors:
            href = a.get("href", "")
            m = _ITEM_URL_RE.search(href)
            if not m:
                continue
            item_id = m.group(1)
            if item_id in seen:
                continue
            seen.add(item_id)

            title = self._clean_text(a.get("title") or a.get_text(" ", strip=True) or "")
            price = 0
            price_span = a.find("span", class_=re.compile(r"number|price"))
            if price_span:
                price = self._parse_price(price_span.get_text())

            img = a.find("img")
            img_url = img.get("src") or img.get("data-src") or "" if img else ""

            items.append(
                PlatformItem(
                    platform=self.platform,
                    item_id=item_id,
                    title=title or f"Mercari {item_id}",
                    price=price,
                    img_url=img_url,
                    item_url=f"{self.base_url}/jp/items/{item_id}",
                    status="在售",
                )
            )
        return items

    @staticmethod
    def _parse_dt(value: Any) -> Optional[datetime]:
        if isinstance(value, (int, float)):
            try:
                return datetime.fromtimestamp(value / 1000 if value > 10**12 else value)
            except (ValueError, OSError):
                return None
        if isinstance(value, str):
            for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
                try:
                    return datetime.strptime(value, fmt)
                except ValueError:
                    continue
        return None
