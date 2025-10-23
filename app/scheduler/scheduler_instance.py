from __future__ import annotations
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.executors.asyncio import AsyncIOExecutor
from pytz import utc
from loguru import logger

from ..config import settings
from apscheduler.triggers.cron import CronTrigger

from .jobs import cleanup_expired_memories_job

# Convert async URL to sync for APScheduler jobstore (it uses sync SQLAlchemy)
job_store_url = settings.DATABASE_URL.replace("+asyncpg", "").replace("postgresql+asyncpg", "postgresql")

jobstores = {
    'default': SQLAlchemyJobStore(url=job_store_url)
}

executors = {
    'default': AsyncIOExecutor()
}

job_defaults = {
    'coalesce': True,  # Combine missed runs
    'max_instances': 1,  # One instance per job
    'misfire_grace_time': 300,  # 5 min grace for missed jobs
}

scheduler = AsyncIOScheduler(
    jobstores=jobstores,
    executors=executors,
    job_defaults=job_defaults,
    timezone=utc,
)

def start_scheduler():
    if not scheduler.running:
        scheduler.start()
        # schedule daily cleanup at 03:00 UTC
        try:
            job_id = "cleanup_expired_memories"
            if not scheduler.get_job(job_id):
                scheduler.add_job(
                    func="app.scheduler.jobs:cleanup_expired_memories_job",
                    trigger=CronTrigger(hour=3, minute=0, timezone=utc),
                    id=job_id,
                    replace_existing=True,
                )
                logger.info("Scheduled cleanup_expired_memories_job at 03:00 UTC")
        except Exception:
            logger.exception("Failed to schedule cleanup job")
        logger.info("APScheduler started")

def shutdown_scheduler():
    if scheduler.running:
        scheduler.shutdown()
        logger.info("APScheduler shut down")