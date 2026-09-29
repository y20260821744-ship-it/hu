"""密码哈希与会话令牌（无第三方依赖，仅用标准库）。

- 密码：PBKDF2-SHA256（60 万次迭代 + 随机盐），存储格式 pbkdf2_sha256$iters$salt$digest
- 会话：签名 Cookie（HMAC-SHA256），内含 user_id 与过期时间；密钥持久化在 data/secret.key
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path

from .config import settings

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

_PBKDF2_ITERATIONS = 600_000
_SESSION_TTL = settings.SESSION_TTL_HOURS * 3600


def _secret_key() -> bytes:
    """加载或生成持久化会话密钥（data/ 已在 .gitignore，不会入库）。"""
    key_file = _DATA_DIR / "secret.key"
    if key_file.exists():
        return key_file.read_bytes()
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(32)
    key_file.write_bytes(key)
    return key


# ---------------- 密码哈希 ----------------

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt, digest = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        computed = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iters)
        ).hex()
        return hmac.compare_digest(computed, digest)
    except (ValueError, TypeError):
        return False


# ---------------- 会话令牌 ----------------

def create_session_token(user_id: int) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps({"uid": user_id, "exp": int(time.time()) + _SESSION_TTL}).encode("utf-8")
    ).decode("ascii")
    sig = hmac.new(_secret_key(), payload.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify_session_token(token: str) -> int | None:
    """校验签名与有效期，返回 user_id；非法或过期返回 None。"""
    try:
        payload, sig = token.split(".")
        expected = hmac.new(_secret_key(), payload.encode("ascii"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
        if int(data["exp"]) < time.time():
            return None
        return int(data["uid"])
    except Exception:  # noqa: BLE001 任何解析失败都视为无效
        return None
