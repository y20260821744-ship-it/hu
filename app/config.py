"""全局配置：从环境变量 / .env 文件加载。

优先级：环境变量 > .env 文件 > 内置默认值。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List


def _load_dotenv() -> None:
    """轻量 .env 加载（不引入额外依赖）。"""
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        # 支持 "KEY=value" 以及带引号的值
        if value[:1] in ('"', "'") and value[-1:] == value[:1]:
            value = value[1:-1]
        os.environ.setdefault(key, value)


_load_dotenv()


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


def _env_list(key: str) -> List[str]:
    raw = _env(key, "")
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


class Settings:
    # ---- 基础 ----
    APP_NAME: str = "JpSecondHandMonitor"
    DEBUG: bool = _env("DEBUG", "0") == "1"
    DATABASE_URL: str = _env("DATABASE_URL", "sqlite:///./data/monitor.db")
    # 面板监听地址
    HOST: str = _env("HOST", "0.0.0.0")
    PORT: int = _env_int("PORT", 8000)

    # ---- 抓取 / 风控 ----
    # 日本 IP 代理池（http 代理，形如 http://user:pass@host:port），逗号分隔多个实现轮换
    PROXY_LIST: List[str] = _env_list("PROXY_LIST")
    # 未配置代理时是否直连（国内 IP 大概率被限流/验证码，建议配置代理）
    ALLOW_DIRECT: bool = _env("ALLOW_DIRECT", "1") == "1"
    REQUEST_TIMEOUT: float = float(_env("REQUEST_TIMEOUT", "20"))
    # 抓取失败退避基准（秒）
    RETRY_BASE_BACKOFF: float = float(_env("RETRY_BASE_BACKOFF", "5"))
    MAX_RETRIES: int = _env_int("MAX_RETRIES", 3)
    # 单平台连续失败达到该次数后自动降频（间隔 x 2，直至最小档）
    FAILURE_DOWNGRADE_THRESHOLD: int = _env_int("FAILURE_DOWNGRADE_THRESHOLD", 3)

    # ---- 通知渠道（未配置的渠道自动跳过）----
    # Telegram
    TELEGRAM_BOT_TOKEN: str = _env("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID: str = _env("TELEGRAM_CHAT_ID")
    # 钉钉群机器人 webhook
    DINGTALK_WEBHOOK: str = _env("DINGTALK_WEBHOOK")
    DINGTALK_SECRET: str = _env("DINGTALK_SECRET")  # 加签密钥，可选
    # Bark (iOS)
    BARK_KEY: str = _env("BARK_KEY")
    BARK_SERVER: str = _env("BARK_SERVER", "https://api.day.app")
    # 企业微信群机器人 webhook
    WECOM_WEBHOOK: str = _env("WECOM_WEBHOOK")
    # PushPlus (微信公众号)
    PUSHPLUS_TOKEN: str = _env("PUSHPLUS_TOKEN")
    PUSHPLUS_TOPIC: str = _env("PUSHPLUS_TOPIC")
    # WxPusher (微信公众号)
    WXPUSHER_APP_TOKEN: str = _env("WXPUSHER_APP_TOKEN")
    WXPUSHER_TOPIC_ID: str = _env("WXPUSHER_TOPIC_ID")
    # Server酱 Turbo (微信公众号)
    SERVERCHAN_SENDKEY: str = _env("SERVERCHAN_SENDKEY")
    # 邮件 SMTP
    SMTP_HOST: str = _env("SMTP_HOST")
    SMTP_PORT: int = _env_int("SMTP_PORT", 465)
    SMTP_USER: str = _env("SMTP_USER")
    SMTP_PASSWORD: str = _env("SMTP_PASSWORD")
    SMTP_FROM: str = _env("SMTP_FROM")
    SMTP_TO: str = _env("SMTP_TO")
    # 通用 Webhook
    WEBHOOK_URL: str = _env("WEBHOOK_URL")

    # ---- 默认监控频率（秒），可在面板/DB 中按平台覆盖 ----
    DEFAULT_INTERVAL: int = _env_int("DEFAULT_INTERVAL", 300)  # 5 分钟
    MIN_INTERVAL: int = _env_int("MIN_INTERVAL", 30)

    # ---- 默认启用渠道（逗号分隔，如 telegram,dingtalk,bark）----
    DEFAULT_CHANNELS: str = _env("DEFAULT_CHANNELS", "telegram,dingtalk,bark")

    # ---- 面板登录账号 ----
    # 首次启动自动创建的管理员账号（务必修改默认密码 admin123）
    ADMIN_USERNAME: str = _env("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD: str = _env("ADMIN_PASSWORD", "admin123")
    # 登录会话有效期（小时）
    SESSION_TTL_HOURS: int = _env_int("SESSION_TTL_HOURS", 168)  # 7 天

    # ---- 汇率（日元→人民币，用于推送展示；可按需更新）----
    JPY_CNY_RATE: float = float(_env("JPY_CNY_RATE", "0.048"))


settings = Settings()
