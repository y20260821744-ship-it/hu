"""APScheduler 调度：每平台独立频率抓取 + 频率变更自动同步 + 手动触发。"""
from __future__ import annotations

import logging
from typing import Dict

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from .adapters import supported_platforms
from .config import settings
from .database import SessionLocal
from .models import Setting
from .service import MonitorService

logger = logging.getLogger(__name__)


class SchedulerManager:
    def __init__(self) -> None:
        self.scheduler = AsyncIOScheduler(timezone="Asia/Tokyo")
        self.service = MonitorService()
        self._job_ids: Dict[str, str] = {}

    def start(self) -> None:
        if self.scheduler.running:
            return
        # 注册各平台抓取任务 + 间隔同步任务
        for platform in supported_platforms():
            self._register_platform_job(platform)
        self.scheduler.add_job(
            self.sync_intervals,
            IntervalTrigger(seconds=30),
            id="sync-intervals",
            replace_existing=True,
        )
        self.scheduler.start()
        logger.info("调度器已启动，平台: %s", supported_platforms())

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    def _register_platform_job(self, platform: str) -> None:
        db = SessionLocal()
        try:
            interval = db.get(Setting, platform).interval if db.get(Setting, platform) else settings.DEFAULT_INTERVAL
        finally:
            db.close()
        interval = max(interval, settings.MIN_INTERVAL)
        job_id = f"scan-{platform}"
        self.scheduler.add_job(
            self._scan_wrapper,
            IntervalTrigger(seconds=interval),
            id=job_id,
            args=[platform],
            replace_existing=True,
            misfire_grace_time=30,
        )
        self._job_ids[platform] = job_id
        logger.info("已注册抓取任务: %s 每 %d 秒", platform, interval)

    async def _scan_wrapper(self, platform: str) -> None:
        try:
            await self.service.scan_platform(platform)
        except Exception as exc:  # noqa: BLE001 单次失败不拖垮调度
            logger.error("[%s] 定时抓取异常: %s", platform, exc)

    def sync_intervals(self) -> None:
        """每 30 秒同步一次各平台频率设置（面板修改后无需重启）。"""
        db = SessionLocal()
        try:
            for platform in supported_platforms():
                setting = db.get(Setting, platform)
                if setting is None:
                    continue
                interval = max(setting.interval, settings.MIN_INTERVAL)
                job = self.scheduler.get_job(self._job_ids.get(platform))
                if job and job.trigger.interval.total_seconds() != interval:
                    self.scheduler.reschedule_job(
                        self._job_ids[platform],
                        trigger=IntervalTrigger(seconds=interval),
                    )
                    logger.info("[%s] 频率已更新为 %d 秒", platform, interval)
        finally:
            db.close()

    async def scan_now(self, platform: str | None = None) -> Dict:
        """手动触发抓取（面板/命令行使用）。"""
        if platform:
            return {platform: await self.service.scan_platform(platform)}
        results = {}
        for p in supported_platforms():
            results[p] = await self.service.scan_platform(p)
        return results
