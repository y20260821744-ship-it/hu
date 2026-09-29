"""核心监控服务：抓取 → 匹配 → 去重入库 → 推送。

流程（对应需求书第 7 节）：
适配器搜索 → 规则匹配（关键词 AND/OR、价格区间、卖家、品牌）→
去重入库（platform+item_id 唯一，仅新商品放行）→ 推送队列 → 多渠道通知
"""
from __future__ import annotations

import logging
from typing import Dict, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from .adapters import get_adapter, init_adapters
from .config import settings
from .database import SessionLocal, init_db
from .matcher import rule_allows, title_matches_any_keyword
from .models import Item, Keyword, PriceHistory, Rule, Setting
from .notifier import NotifierManager, NotifyMessage

logger = logging.getLogger(__name__)

_PLATFORM_NAMES = {
    "mercari": "煤炉 Mercari",
    "suruga": "骏河屋 Suruga-ya",
}


def platform_display_name(platform: str) -> str:
    return _PLATFORM_NAMES.get(platform, platform)


class MonitorService:
    def __init__(self) -> None:
        init_adapters()
        self.notifier = NotifierManager()

    # ---------------- 平台设置 ----------------

    def get_setting(self, db: Session, platform: str) -> Setting:
        setting = db.get(Setting, platform)
        if setting is None:
            setting = Setting(
                platform=platform,
                interval=settings.DEFAULT_INTERVAL,
                proxy_mode="auto",
                channels=settings.DEFAULT_CHANNELS,
            )
            db.add(setting)
            db.commit()
        return setting

    def channel_names(self, db: Session, platform: str) -> List[str]:
        setting = self.get_setting(db, platform)
        raw = (setting.channels or settings.DEFAULT_CHANNELS).strip()
        return [c.strip() for c in raw.split(",") if c.strip()]

    # ---------------- 单平台扫描 ----------------

    async def scan_platform(self, platform: str, db: Session | None = None) -> Dict:
        """抓取并处理一个平台。返回统计信息。"""
        close_db = db is None
        db = db or SessionLocal()
        try:
            adapter = get_adapter(platform)
            setting = self.get_setting(db, platform)

            keywords = db.scalars(
                select(Keyword).where(Keyword.enabled.is_(True)).order_by(Keyword.id)
            ).all()
            rules = db.scalars(select(Rule).where(Rule.enabled.is_(True))).all()

            stats = {
                "platform": platform,
                "keywords": len(keywords),
                "scanned": 0,
                "matched": 0,
                "new_items": 0,
                "pushed": 0,
                "errors": 0,
            }

            if not keywords:
                logger.info("[%s] 没有启用的关键词，跳过", platform)
                return stats

            # 多关键词并行抓取
            import asyncio

            tasks = [adapter.search(kw.keyword) for kw in keywords]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            new_items: List[Item] = []
            for kw, result in zip(keywords, results):
                if isinstance(result, BaseException):
                    stats["errors"] += 1
                    logger.error("[%s] 关键词 %r 抓取失败: %s", platform, kw.keyword, result)
                    continue

                for item in result:
                    stats["scanned"] += 1
                    if not title_matches_any_keyword(item.title, [kw]):
                        continue
                    if not rule_allows(
                        platform, item.title, item.price, item.seller, rules
                    ):
                        continue
                    stats["matched"] += 1

                    # 去重核心：platform+item_id 唯一
                    exists = db.execute(
                        select(Item.id).where(
                            Item.platform == platform,
                            Item.item_id == item.item_id,
                        )
                    ).first()
                    if exists:
                        continue

                    row = Item(
                        platform=platform,
                        item_id=item.item_id,
                        title=item.title[:500],
                        price=item.price,
                        seller=item.seller[:200],
                        img_url=item.img_url[:1000],
                        item_url=item.item_url[:1000],
                        listed_at=item.listed_at,
                        status=item.status,
                    )
                    db.add(row)
                    db.flush()
                    db.add(PriceHistory(item_id=row.id, price=item.price))
                    new_items.append(row)
                    stats["new_items"] += 1

            db.commit()

            # 推送新商品
            for row in new_items:
                channels = self.channel_names(db, platform)
                msg = NotifyMessage(
                    platform=platform,
                    platform_name=platform_display_name(platform),
                    item_id=row.item_id,
                    title=row.title,
                    price_jpy=row.price,
                    price_cny=round(row.price * settings.JPY_CNY_RATE, 1),
                    seller=row.seller,
                    img_url=row.img_url,
                    item_url=row.item_url,
                    status=row.status,
                )
                if channels:
                    results = await self.notifier.notify(msg, channels, row.id, db)
                    stats["pushed"] += sum(1 for v in results.values() if v == "success")

            # 降频告警信息
            fetcher = adapter.fetcher if hasattr(adapter, "fetcher") else None
            if fetcher:
                throttle = fetcher.throttle_for(platform)
                stats["downgraded"] = throttle.downgraded
                stats["consecutive_failures"] = throttle.consecutive_failures

            logger.info(
                "[%s] 扫描完成: 抓取=%d 命中=%d 新增=%d 推送成功=%d 错误=%d",
                platform,
                stats["scanned"],
                stats["matched"],
                stats["new_items"],
                stats["pushed"],
                stats["errors"],
            )
            return stats
        finally:
            if close_db:
                db.close()

    async def scan_all(self) -> Dict[str, Dict]:
        """扫描全部已注册平台。"""
        from .adapters import supported_platforms

        results = {}
        for platform in supported_platforms():
            results[platform] = await self.scan_platform(platform)
        return results
