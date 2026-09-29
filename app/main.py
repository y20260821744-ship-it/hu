"""FastAPI 应用：Web 管理面板 + 后台调度。

面板功能：登录鉴权（账号体系）、仪表盘、关键词管理、规则管理、命中记录、
平台设置（频率/渠道）、代理池管理（增删/启停/测试）、账号管理（管理员）、
推送日志、手动触发抓取。
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional
from urllib.parse import quote

import httpx
from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, func, select

from . import models, security
from .adapters import all_adapters, supported_platforms
from .config import settings
from .crawler.fetcher import bump_proxy_pool
from .database import SessionLocal, init_db
from .scheduler import SchedulerManager

logging.basicConfig(level=logging.DEBUG if settings.DEBUG else logging.INFO)
logger = logging.getLogger(__name__)

scheduler_mgr = SchedulerManager()

SESSION_COOKIE = "monitor_session"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    ensure_default_admin()
    scheduler_mgr.start()
    yield
    scheduler_mgr.shutdown()


def ensure_default_admin() -> None:
    """首次启动创建默认管理员（.env 的 ADMIN_USERNAME / ADMIN_PASSWORD）。"""
    db = SessionLocal()
    try:
        exists = db.scalar(select(func.count(models.User.id))) or 0
        if exists == 0:
            db.add(
                models.User(
                    username=settings.ADMIN_USERNAME,
                    password_hash=security.hash_password(settings.ADMIN_PASSWORD),
                    role="admin",
                    enabled=True,
                )
            )
            db.commit()
            logger.warning(
                "已创建默认管理员 %r，请尽快在「账号管理」页修改默认密码",
                settings.ADMIN_USERNAME,
            )
    finally:
        db.close()


app = FastAPI(title="日本二手平台上新监控系统", lifespan=lifespan)

templates = Jinja2Templates(directory=str(__import__("pathlib").Path(__file__).resolve().parent / "templates"))


# ---------------- 登录鉴权 ----------------

def current_user(request: Request) -> models.User | None:
    """从签名 Cookie 解析当前登录用户；未登录/失效/被停用返回 None。"""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    uid = security.verify_session_token(token)
    if uid is None:
        return None
    db = SessionLocal()
    try:
        user = db.get(models.User, uid)
        if user is None or not user.enabled:
            return None
        return user
    finally:
        db.close()


def _require_login(request: Request):
    """页面路由守卫：未登录跳转登录页；已登录返回 User。"""
    user = current_user(request)
    if user is None:
        return RedirectResponse("/login?next=" + quote(request.url.path), status_code=303)
    return user


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, msg: Optional[str] = Query(None)):
    if current_user(request) is not None:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"page": "login", "msg": msg or ""},
    )


@app.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
):
    user: models.User | None = None
    db = SessionLocal()
    try:
        row = db.scalar(
            select(models.User).where(models.User.username == username.strip())
        )
        if row and row.enabled and security.verify_password(password, row.password_hash):
            row.last_login_at = datetime.now()
            db.commit()
            user = row
    finally:
        db.close()

    if user is None:
        # 统一错误提示 + 延迟，减缓暴力破解
        await asyncio.sleep(0.5)
        return RedirectResponse("/login?msg=" + quote("用户名或密码错误，或账号已被停用"), status_code=303)

    token = security.create_session_token(user.id)
    resp = RedirectResponse("/" if next in ("", "/") else next, status_code=303)
    resp.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        max_age=settings.SESSION_TTL_HOURS * 3600,
    )
    return resp


@app.get("/logout")
async def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(SESSION_COOKIE)
    return resp


# ---------------- 页面 ----------------

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    user = _require_login(request)
    if isinstance(user, RedirectResponse):
        return user
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
                "user": user,
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
    user = _require_login(request)
    if isinstance(user, RedirectResponse):
        return user
    db = SessionLocal()
    try:
        keywords = db.scalars(select(models.Keyword).order_by(models.Keyword.id)).all()
        return templates.TemplateResponse(
            request,
            "keywords.html",
            {"page": "keywords", "user": user, "keywords": keywords},
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
    user = _require_login(request)
    if isinstance(user, RedirectResponse):
        return user
    db = SessionLocal()
    try:
        rules = db.scalars(select(models.Rule).order_by(models.Rule.id)).all()
        return templates.TemplateResponse(
            request,
            "rules.html",
            {
                "page": "rules",
                "user": user,
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
    user = _require_login(request)
    if isinstance(user, RedirectResponse):
        return user
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
                "user": user,
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
    user = _require_login(request)
    if isinstance(user, RedirectResponse):
        return user
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
            {"page": "settings", "user": user, "rows": rows, "all_channels": ALL_CHANNEL_NAMES},
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
    user = _require_login(request)
    if isinstance(user, RedirectResponse):
        return user
    db = SessionLocal()
    try:
        logs = db.scalars(select(models.PushLog).order_by(desc(models.PushLog.id)).limit(200)).all()
        return templates.TemplateResponse(
            request,
            "logs.html",
            {"page": "logs", "user": user, "logs": logs},
        )
    finally:
        db.close()


# ---------------- 代理池管理 ----------------

def _mask_proxy(url: str) -> str:
    """展示时隐藏代理的用户名/密码（只留 协议://***@host:port）。"""
    try:
        from urllib.parse import urlsplit, urlunsplit

        parts = urlsplit(url)
        if parts.username is not None:
            host = parts.hostname or ""
            if parts.port:
                host = f"{host}:{parts.port}"
            return urlunsplit((parts.scheme, f"***@{host}", parts.path, parts.query, parts.fragment))
    except Exception:  # noqa: BLE001
        pass
    return url


@app.get("/proxies", response_class=HTMLResponse)
async def proxies_page(request: Request, msg: Optional[str] = Query(None)):
    user = _require_login(request)
    if isinstance(user, RedirectResponse):
        return user
    db = SessionLocal()
    try:
        proxies = db.scalars(select(models.Proxy).order_by(models.Proxy.id)).all()
        return templates.TemplateResponse(
            request,
            "proxies.html",
            {
                "page": "proxies",
                "user": user,
                "proxies": proxies,
                "msg": msg or "",
                "mask_proxy": _mask_proxy,
                "env_proxies": settings.PROXY_LIST,
            },
        )
    finally:
        db.close()


@app.post("/proxies")
async def add_proxy(url: str = Form(...), remark: str = Form("")):
    db = SessionLocal()
    try:
        clean = _restore_utf8(url).strip()
        if not clean:
            return RedirectResponse("/proxies?msg=" + quote("代理地址不能为空"), status_code=303)
        if not clean.startswith(("http://", "https://", "socks5://", "socks5h://")):
            clean = "http://" + clean
        db.add(models.Proxy(url=clean, remark=_restore_utf8(remark).strip(), enabled=True))
        db.commit()
    finally:
        db.close()
    bump_proxy_pool()
    return RedirectResponse("/proxies?msg=" + quote("已添加，抓取层已生效（无需重启）"), status_code=303)


@app.post("/proxies/{pid}/toggle")
async def toggle_proxy(pid: int):
    db = SessionLocal()
    try:
        proxy = db.get(models.Proxy, pid)
        if proxy:
            proxy.enabled = not proxy.enabled
            db.commit()
    finally:
        db.close()
    bump_proxy_pool()
    return RedirectResponse("/proxies?msg=" + quote("已更新启用状态"), status_code=303)


@app.post("/proxies/{pid}/delete")
async def delete_proxy(pid: int):
    db = SessionLocal()
    try:
        proxy = db.get(models.Proxy, pid)
        if proxy:
            db.delete(proxy)
            db.commit()
    finally:
        db.close()
    bump_proxy_pool()
    return RedirectResponse("/proxies?msg=" + quote("已删除"), status_code=303)


@app.post("/proxies/{pid}/test")
async def test_proxy(pid: int):
    """通过该代理访问 ipify 获取出口 IP，验证连通性。"""
    db = SessionLocal()
    try:
        proxy = db.get(models.Proxy, pid)
        if proxy is None:
            return RedirectResponse("/proxies?msg=" + quote("代理不存在"), status_code=303)
        url = proxy.url
    finally:
        db.close()

    exit_ip = ""
    try:
        async with httpx.AsyncClient(proxy=url, timeout=15, follow_redirects=True) as client:
            resp = await client.get("https://api.ipify.org?format=json")
            resp.raise_for_status()
            exit_ip = resp.json().get("ip", "?")
    except Exception as exc:  # noqa: BLE001 连通失败
        db = SessionLocal()
        try:
            p = db.get(models.Proxy, pid)
            if p:
                p.fail_count += 1
                db.commit()
        finally:
            db.close()
        return RedirectResponse(
            "/proxies?msg=" + quote(f"测试失败：{str(exc)[:120]}"), status_code=303
        )

    db = SessionLocal()
    try:
        p = db.get(models.Proxy, pid)
        if p:
            p.fail_count = 0
            p.last_ok_at = datetime.now()
            db.commit()
    finally:
        db.close()
    return RedirectResponse(
        "/proxies?msg=" + quote(f"测试成功，出口 IP: {exit_ip}"), status_code=303
    )


# ---------------- 账号管理（仅管理员） ----------------

def _require_admin(request: Request):
    """管理员守卫：未登录跳登录页；普通账号跳回首页。"""
    user = current_user(request)
    if user is None:
        return RedirectResponse("/login?next=" + quote(request.url.path), status_code=303)
    if user.role != "admin":
        return RedirectResponse("/", status_code=303)
    return user


@app.get("/accounts", response_class=HTMLResponse)
async def accounts_page(request: Request, msg: Optional[str] = Query(None)):
    user = _require_admin(request)
    if isinstance(user, RedirectResponse):
        return user
    db = SessionLocal()
    try:
        users = db.scalars(select(models.User).order_by(models.User.id)).all()
        # 默认管理员密码未改时给出提醒
        default_admin = next(
            (u for u in users if u.username == settings.ADMIN_USERNAME), None
        )
        is_default_pw = bool(
            default_admin and security.verify_password(settings.ADMIN_PASSWORD, default_admin.password_hash)
        )
        return templates.TemplateResponse(
            request,
            "accounts.html",
            {
                "page": "accounts",
                "user": user,
                "users": users,
                "msg": msg or "",
                "is_default_pw": is_default_pw,
                "default_username": settings.ADMIN_USERNAME,
            },
        )
    finally:
        db.close()


@app.post("/accounts")
async def add_account(
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form("user"),
):
    db = SessionLocal()
    try:
        name = _restore_utf8(username).strip()
        if not name or len(password) < 6:
            return RedirectResponse("/accounts?msg=" + quote("用户名不能为空，密码至少 6 位"), status_code=303)
        exists = db.scalar(
            select(models.User.id).where(models.User.username == name)
        )
        if exists:
            return RedirectResponse("/accounts?msg=" + quote("该用户名已存在"), status_code=303)
        db.add(
            models.User(
                username=name,
                password_hash=security.hash_password(password),
                role="admin" if role == "admin" else "user",
                enabled=True,
            )
        )
        db.commit()
    finally:
        db.close()
    return RedirectResponse("/accounts?msg=" + quote("账号已创建"), status_code=303)


def _last_admin_count(db) -> int:
    return db.scalar(
        select(func.count(models.User.id)).where(
            models.User.role == "admin", models.User.enabled.is_(True)
        )
    ) or 0


@app.post("/accounts/{uid}/toggle")
async def toggle_account(uid: int, request: Request):
    admin = _require_admin(request)
    if isinstance(admin, RedirectResponse):
        return admin
    db = SessionLocal()
    try:
        target = db.get(models.User, uid)
        if target is None:
            return RedirectResponse("/accounts?msg=" + quote("账号不存在"), status_code=303)
        if target.id == admin.id:
            return RedirectResponse("/accounts?msg=" + quote("不能停用自己"), status_code=303)
        if target.role == "admin" and target.enabled and _last_admin_count(db) <= 1:
            return RedirectResponse("/accounts?msg=" + quote("至少保留一个启用中的管理员"), status_code=303)
        target.enabled = not target.enabled
        db.commit()
    finally:
        db.close()
    return RedirectResponse("/accounts?msg=" + quote("已更新启用状态"), status_code=303)


@app.post("/accounts/{uid}/password")
async def reset_account_password(uid: int, request: Request, password: str = Form(...)):
    admin = _require_admin(request)
    if isinstance(admin, RedirectResponse):
        return admin
    if len(password) < 6:
        return RedirectResponse("/accounts?msg=" + quote("新密码至少 6 位"), status_code=303)
    db = SessionLocal()
    try:
        target = db.get(models.User, uid)
        if target is None:
            return RedirectResponse("/accounts?msg=" + quote("账号不存在"), status_code=303)
        target.password_hash = security.hash_password(password)
        db.commit()
    finally:
        db.close()
    return RedirectResponse("/accounts?msg=" + quote("密码已重置"), status_code=303)


@app.post("/accounts/{uid}/delete")
async def delete_account(uid: int, request: Request):
    admin = _require_admin(request)
    if isinstance(admin, RedirectResponse):
        return admin
    db = SessionLocal()
    try:
        target = db.get(models.User, uid)
        if target is None:
            return RedirectResponse("/accounts?msg=" + quote("账号不存在"), status_code=303)
        if target.id == admin.id:
            return RedirectResponse("/accounts?msg=" + quote("不能删除自己"), status_code=303)
        if target.role == "admin" and target.enabled and _last_admin_count(db) <= 1:
            return RedirectResponse("/accounts?msg=" + quote("至少保留一个启用中的管理员"), status_code=303)
        db.delete(target)
        db.commit()
    finally:
        db.close()
    return RedirectResponse("/accounts?msg=" + quote("账号已删除"), status_code=303)


# ---------------- API ----------------

@app.get("/api/stats")
async def api_stats(request: Request):
    user = current_user(request)
    if user is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
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
async def api_scan(request: Request, platform: Optional[str] = Form(None)):
    """手动触发一次抓取（前台异步执行）。"""
    user = current_user(request)
    if user is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

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
