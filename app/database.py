"""数据库引擎与会话管理（SQLAlchemy 2.x，默认 SQLite）。"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


def _ensure_sqlite_dir(url: str) -> None:
    """SQLite 文件路径的父目录不存在时自动创建。"""
    if url.startswith("sqlite:///"):
        raw = url.replace("sqlite:///", "", 1)
        if raw != ":memory:":
            Path(raw).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_dir(settings.DATABASE_URL)

connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(
    settings.DATABASE_URL,
    echo=False,
    connect_args=connect_args,
    pool_pre_ping=True,
)


# SQLite 开启 WAL 与外键，避免并发读写锁冲突
@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):  # noqa: ANN001
    if settings.DATABASE_URL.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class SessionLocal:
    pass


def init_db() -> None:
    """建表（幂等）。"""
    from . import models  # noqa: F401  确保模型已注册

    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI 依赖：提供会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def session_scope():
    """上下文管理器形式的会话。"""
    from contextlib import contextmanager

    @contextmanager
    def _cm():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    return _cm()
