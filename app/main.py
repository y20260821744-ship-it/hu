"""FastAPI 应用：Web 管理面板 + 后台调度。

面板功能：仪表盘（监控状态/统计）、关键词管理、规则管理、命中记录、
平台设置（频率/渠道）、推送日志、手动触发抓取。
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, func, select

from . import models
from .adapters import all_adapters, supported_platforms
from .config import settings
from .database import SessionLocal, init_db
from .scheduler import SchedulerManager

logging.basicConfig(level=logging.DEBUG if settings.DEBUG else logging.INFO)
logger = logging.getLogger(__name__)

scheduler_mgr = SchedulerManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler_mgr.start()
    yield
    scheduler_mgr.shutdown()


app = FastAPI(title="日本二手平台上新监控系统", lifespan=lifespan)

templates = Jinja2Templates(directory=str(__import__("pathlib").Path(__file__).resolve().parent / "templates"))


# ---------------- 页面 ----------------

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    db = SessionLocal()
    try:
        total_items = db.scalar(select(func.count(models.Item.id))) or 0
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_new = db.scalar(
            select(func.count(models.Item.id)).where(models.Item.first_seen_at >= today_start)
        ) or 0
        total_keywords = db.scalar(select(func.count(models.Keyword.id))) or 0
        enabled_keywords = db.scalar(
            select(func.count(models.Keyword.id)).where(models.Keyword.enabled.is_(True))
        ) or 0
        total_rules = db.scalar(select(func.count(models.Rule.id))) or 0

        platform_stats = []
        for p in supported_platforms():
            setting = db.get(models.Setting, p)
            count = db.scalar(
                select(func.count(models.Item.id)).where(models.Item.platform == p)
            ) or 0
            adapter = next((a for a in all_adapters() if a.platform == p), None)
            fetcher = getattr(adapter, "fetcher", None)
            throttle = fetcher.throttle_for(p) if fetcher else None
            platform_stats.append(
                {
                    "platform": p,
                    "name": getattr(adapter, "display_name", p),
                    "interval": setting.interval if setting else settings.DEFAULT_INTERVAL,
                    "channels": setting.channels if setting else settings.DEFAULT_CHANNELS,
                    "items": count,
                    "downgraded": throttle.downgraded if throttle else False,
                    "failures": throttle.consecutive_failures if throttle else 0,
                }
            )

        recent_items = db.scalars(
            select(models.Item).order_by(desc(models.Item.first_seen_at)).limit(10)
        ).all()
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "page": "dashboard",
                "stats": {
                    "total_items": total_items,
                    "today_new": today_new,
                    "total_keywords": total_keywords,
                    "enabled_keywords": enabled_keywords,
                    "total_rules": total_rules,
                },
                "platform_stats": platform_stats,
                "recent_items": recent_items,
                "display_name": _display_name,
            },
        )
    finally:
        db.close()


@app.get("/keywords", response_class=HTMLResponse)
async def keywords_page(request: Request):
    db = SessionLocal()
    try:
        keywords = db.scalars(select(models.Keyword).order_by(models.Keyword.id)).all()
        return templates.TemplateResponse(
            request,
            "keywords.html",
            {"page": "keywords", "keywords": keywords},
        )
    finally:
        db.close()


def _restore_utf8(s: str) -> str:
    """修复表单按 latin-1 解码导致的日文/中文乱码（mojibake）。

    Starlette 解析 x-www-form-urlencoded 时按 latin-1 解码字节，日文/中文会变成
    'ã\x83\x95...' 这类乱码。此处把乱码还原为 UTF-8：将字符串按 latin-1 编码
    还原为原始字节，再按 UTF-8 解码；仅当解码成功且结果包含非 latin-1 字符时替换。
    """
    try:
        restored = s.encode("latin-1").decode("utf-8")
        if restored != s and any(ord(ch) > 0x7F for ch in restored):
            return restored
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return s


@app.post("/keywords")
async def add_keyword(
    keyword: str = Form(...),
    lang: str = Form("ja"),
    brand_tag: str = Form(""),
    model_tag: str = Form(""),
    category: str = Form(""),
):
    db = SessionLocal()
    try:
        db.add(
            models.Keyword(
                keyword=_restore_utf8(keyword).strip(),
                lang=lang,
                brand_tag=_restore_utf8(brand_tag).strip(),
                model_tag=_restore_utf8(model_tag).strip(),
                category=_restore_utf8(category).strip(),
                enabled=True,
            )
        )
        db.commit()
    finally:
        db.close()
    return RedirectResponse("/keywords", status_code=303)


@app.post("/keywords/{kid}/toggle")
async def toggle_keyword(kid: int):
    db = SessionLocal()
    try:
        kw = db.get(models.Keyword, kid)
        if kw:
            kw.enabled = not kw.enabled
            db.commit()
    finally:
        db.close()
    return RedirectResponse("/keywords", status_code=303)


@app.post("/keywords/{kid}/delete")
async def delete_keyword(kid: int):
    db = SessionLocal()
    try:
        kw = db.get(models.Keyword, kid)
        if kw:
            db.delete(kw)
            db.commit()
    finally:
        db.close()
    return RedirectResponse("/keywords", status_code=303)


@app.get("/rules", response_class=HTMLResponse)
async def rules_page(request: Request):
    db = SessionLocal()
    try:
        rules = db.scalars(select(models.Rule).order_by(models.Rule.id)).all()
        return templates.TemplateResponse(
            request,
            "rules.html",
            {
                "page": "rules",
                "rules": rules,
                "platforms": supported_platforms(),
            },
        )
    finally:
        db.close()


@app.post("/rules")
async def add_rule(
    platform: str = Form(""),
    price_min: str = Form(""),
    price_max: str = Form(""),
    seller_id: str = Form(""),
    brand: str = Form(""),
):
    db = SessionLocal()
    try:
        db.add(
            models.Rule(
                platform=_restore_utf8(platform).strip(),
                price_min=int(price_min) if price_min.strip().isdigit() else None,
                price_max=int(price_max) if price_max.strip().isdigit() else None,
                seller_id=_restore_utf8(seller_id).strip(),
                brand=_restore_utf8(brand).strip(),
                enabled=True,
            )
        )
        db.commit()
    finally:
        db.close()
    return RedirectResponse("/rules", status_code=303)


@app.post("/rules/{rid}/toggle")
async def toggle_rule(rid: int):
    db = SessionLocal()
    try:
        r = db.get(models.Rule, rid)
        if r:
            r.enabled = not r.enabled
            db.commit()
    finally:
        db.close()
    return RedirectResponse("/rules", status_code=303)


@app.post("/rules/{rid}/delete")
async def delete_rule(rid: int):
    db = SessionLocal()
    try:
        r = db.get(models.Rule, rid)
        if r:
            db.delete(r)
            db.commit()
    finally:
        db.close()
    return RedirectResponse("/rules", status_code=303)


@app.get("/items", response_class=HTMLResponse)
async def items_page(
    request: Request,
    platform: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
):
    db = SessionLocal()
    try:
        q = select(models.Item).order_by(desc(models.Item.first_seen_at))
        if platform:
            q = q.where(models.Item.platform == platform)
        total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
        per_page = 50
        items = db.scalars(q.offset((page - 1) * per_page).limit(per_page)).all()
        pages = max(1, (total + per_page - 1) // per_page)
        return templates.TemplateResponse(
            request,
            "items.html",
            {
                "page": "items",
                "items": items,
                "platforms": supported_platforms(),
                "cur_platform": platform or "",
                "total": total,
                "page": page,
                "pages": pages,
            },
        )
    finally:
        db.close()


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    db = SessionLocal()
    try:
        rows = []
        for p in supported_platforms():
            setting = db.get(models.Setting, p)
            adapter = next((a for a in all_adapters() if a.platform == p), None)
            rows.append(
                {
                    "platform": p,
                    "name": getattr(adapter, "display_name", p),
                    "interval": setting.interval if setting else settings.DEFAULT_INTERVAL,
                    "proxy_mode": setting.proxy_mode if setting else "auto",
                    "channels": setting.channels if setting else settings.DEFAULT_CHANNELS,
                }
            )
        return templates.TemplateResponse(
            request,
            "settings.html",
            {"page": "settings", "rows": rows, "all_channels": ALL_CHANNEL_NAMES},
        )
    finally:
        db.close()


@app.post("/settings/{platform}")
async def update_setting(
    platform: str,
    interval: int = Form(...),
    proxy_mode: str = Form("auto"),
    channels: str = Form(""),
):
    db = SessionLocal()
    try:
        setting = db.get(models.Setting, platform)
        if setting is None:
            setting = models.Setting(platform=platform)
            db.add(setting)
        setting.interval = max(interval, settings.MIN_INTERVAL)
        setting.proxy_mode = proxy_mode
        setting.channels = channels.strip().strip(",")
        db.commit()
    finally:
        db.close()
    # 立即同步调度
    scheduler_mgr.sync_intervals()
    return RedirectResponse("/settings", status_code=303)


@app.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request):
    db = SessionLocal()
    try:
        logs = db.scalars(select(models.PushLog).order_by(desc(models.PushLog.id)).limit(200)).all()
        return templates.TemplateResponse(
            request,
            "logs.html",
            {"page": "logs", "logs": logs},
        )
    finally:
        db.close()


# ---------------- API ----------------

@app.get("/api/stats")
async def api_stats():
    db = SessionLocal()
    try:
        total_items = db.scalar(select(func.count(models.Item.id))) or 0
        total_keywords = db.scalar(select(func.count(models.Keyword.id))) or 0
        success_push = db.scalar(
            select(func.count(models.PushLog.id)).where(models.PushLog.status == "success")
        ) or 0
        failed_push = db.scalar(
            select(func.count(models.PushLog.id)).where(models.PushLog.status == "failed")
        ) or 0
        return JSONResponse(
            {
                "total_items": total_items,
                "total_keywords": total_keywords,
                "push_success": success_push,
                "push_failed": failed_push,
            }
        )
    finally:
        db.close()


@app.post("/api/scan")
async def api_scan(platform: Optional[str] = Form(None)):
    """手动触发一次抓取（前台异步执行）。"""
    import asyncio

    async def run():
        try:
            return await scheduler_mgr.scan_now(platform)
        except Exception as exc:  # noqa: BLE001
            logger.error("手动抓取失败: %s", exc)
            return {"error": str(exc)}

    # 立即执行并返回结果（单平台扫描通常数秒内完成）
    result = await run()
    return JSONResponse(result)


# ---------------- 工具 ----------------

ALL_CHANNEL_NAMES = [
    "telegram",
    "dingtalk",
    "bark",
    "wecom",
    "pushplus",
    "wxpusher",
    "serverchan",
    "email",
    "webhook",
]


def _display_name(platform: str) -> str:
    from .service import platform_display_name

    return platform_display_name(platform)
