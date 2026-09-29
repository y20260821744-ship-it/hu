"""命令行入口。

用法：
  python run.py once                # 全平台抓取一次（打印统计）
  python run.py scan -p mercari     # 指定平台抓取一次
  python run.py serve               # 启动 Web 面板 + 后台调度
  python run.py addkw "关键词" [lang]  # 快速添加监控关键词
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from app.config import settings
from app.database import SessionLocal, init_db
from app.models import Keyword

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def cmd_addkw(keyword: str, lang: str) -> None:
    init_db()
    db = SessionLocal()
    try:
        db.add(Keyword(keyword=keyword.strip(), lang=lang, enabled=True))
        db.commit()
        print(f"✅ 已添加关键词: {keyword} [{lang}]")
    finally:
        db.close()


async def cmd_scan(platform: str | None) -> None:
    from app.adapters import init_adapters
    from app.service import MonitorService

    init_db()
    init_adapters()
    service = MonitorService()
    if platform:
        result = await service.scan_platform(platform)
        print(f"\n[{platform}] 扫描完成: {result}")
    else:
        results = await service.scan_all()
        for p, r in results.items():
            print(f"[{p}] 抓取={r['scanned']} 命中={r['matched']} 新增={r['new_items']} 推送成功={r['pushed']} 错误={r['errors']}")


def cmd_serve() -> None:
    import uvicorn

    from app.main import app

    print(f"🛰 启动面板: http://{settings.HOST}:{settings.PORT}")
    uvicorn.run(app, host=settings.HOST, port=settings.PORT, log_level="info")


def main() -> None:
    parser = argparse.ArgumentParser(description="日本二手平台上新监控系统")
    sub = parser.add_subparsers(dest="command")

    p_once = sub.add_parser("once", help="全平台抓取一次")
    p_scan = sub.add_parser("scan", help="指定平台抓取一次")
    p_scan.add_argument("-p", "--platform", default=None, help="平台: mercari / suruga，不填则全部")
    sub.add_parser("serve", help="启动 Web 面板 + 后台调度")
    p_add = sub.add_parser("addkw", help="快速添加关键词")
    p_add.add_argument("keyword")
    p_add.add_argument("lang", nargs="?", default="ja")

    args = parser.parse_args()
    if args.command == "addkw":
        cmd_addkw(args.keyword, args.lang)
    elif args.command == "scan":
        asyncio.run(cmd_scan(args.platform))
    elif args.command == "once":
        asyncio.run(cmd_scan(None))
    elif args.command == "serve":
        cmd_serve()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
