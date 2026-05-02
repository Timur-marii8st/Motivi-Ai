from __future__ import annotations
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.executors.asyncio import AsyncIOExecutor
from pytz import utc
from loguru import logger

from ..config import settings
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

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
        
        # Schedule daily cleanup at 03:00 UTC
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
        
        # Schedule daily conversation archiving at 03:30 UTC
        try:
            job_id = "archive_conversations"
            if not scheduler.get_job(job_id):
                scheduler.add_job(
                    func="app.scheduler.jobs:archive_raw_conversations_job",
                    trigger=CronTrigger(hour=3, minute=30, timezone=utc),
                    id=job_id,
                    replace_existing=True,
                )
                logger.info("Scheduled archive_raw_conversations_job at 03:30 UTC")
        except Exception:
            logger.exception("Failed to schedule archive conversations job")

        try:
            job_id = "userbot_followup_check"
            if not scheduler.get_job(job_id):
                scheduler.add_job(
                    func="app.scheduler.jobs:userbot_followup_check_job",
                    trigger=IntervalTrigger(
                        minutes=settings.USERBOT_FOLLOWUP_CHECK_INTERVAL_MINUTES,
                        timezone=utc,
                    ),
                    id=job_id,
                    replace_existing=True,
                )
                logger.info(
                    "Scheduled userbot_followup_check_job every {} minutes",
                    settings.USERBOT_FOLLOWUP_CHECK_INTERVAL_MINUTES,
                )
        except Exception:
            logger.exception("Failed to schedule userbot follow-up check job")
        
        logger.info("APScheduler started")

def shutdown_scheduler():
    if scheduler.running:
        scheduler.shutdown()
        logger.info("APScheduler shut down")
