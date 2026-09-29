"""ORM 数据模型。

设计要点：
- items 表以 (platform, item_id) 唯一索引做去重核心；
- 每个平台监控频率、启用渠道等配置放在 settings 表。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class Keyword(Base):
    """监控关键词。lang: ja / zh / en；brand_tag/model_tag/category 用于组合匹配。"""

    __tablename__ = "keywords"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    keyword: Mapped[str] = mapped_column(String(200), nullable=False)
    lang: Mapped[str] = mapped_column(String(8), default="ja")
    brand_tag: Mapped[str] = mapped_column(String(100), default="")
    model_tag: Mapped[str] = mapped_column(String(100), default="")
    category: Mapped[str] = mapped_column(String(100), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Keyword {self.keyword!r} [{self.lang}] enabled={self.enabled}>"


class Rule(Base):
    """高级监控规则：价格区间 / 指定卖家 / 指定品牌，可按平台生效。"""

    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(50), default="")  # 空 = 全部平台
    price_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seller_id: Mapped[str] = mapped_column(String(200), default="")  # 指定卖家 ID/名称
    brand: Mapped[str] = mapped_column(String(100), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Rule platform={self.platform} price={self.price_min}-{self.price_max}>"


class Item(Base):
    """抓取到的商品（去重核心：platform + item_id 唯一）。"""

    __tablename__ = "items"
    __table_args__ = (
        UniqueConstraint("platform", "item_id", name="uq_platform_item"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    item_id: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(500), default="")
    price: Mapped[int] = mapped_column(Integer, default=0)  # 日元
    seller: Mapped[str] = mapped_column(String(200), default="")
    img_url: Mapped[str] = mapped_column(String(1000), default="")
    item_url: Mapped[str] = mapped_column(String(1000), default="")
    listed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="在售")  # 在售/售出/竞拍中
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Item {self.platform}:{self.item_id} ¥{self.price} {self.title[:20]}>"


class PushLog(Base):
    """推送日志。"""

    __tablename__ = "push_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(Integer, index=True)
    channel: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # success/failed
    error: Mapped[str] = mapped_column(Text, default="")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    pushed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PushLog item={self.item_id} {self.channel} {self.status}>"


class PriceHistory(Base):
    """价格历史（趋势统计用）。"""

    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(Integer, index=True)
    price: Mapped[int] = mapped_column(Integer)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Setting(Base):
    """平台级配置：抓取间隔、代理模式、启用渠道。"""

    __tablename__ = "settings"

    platform: Mapped[str] = mapped_column(String(50), primary_key=True)
    interval: Mapped[int] = mapped_column(Integer, default=300)  # 秒
    proxy_mode: Mapped[str] = mapped_column(String(20), default="auto")  # auto/direct/proxy
    channels: Mapped[str] = mapped_column(String(500), default="")  # 逗号分隔
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Setting {self.platform} interval={self.interval}s>"


class Seller(Base):
    """重点关注卖家名单。"""

    __tablename__ = "sellers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(50), default="")
    seller_id: Mapped[str] = mapped_column(String(200))
    seller_name: Mapped[str] = mapped_column(String(200), default="")
    note: Mapped[str] = mapped_column(String(500), default="")
