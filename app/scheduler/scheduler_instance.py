from __future__ import annotations
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.executors.asyncio import AsyncIOExecutor
from pytz import utc
from loguru import logger

from ..config import settings

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
        logger.info("APScheduler started")

def shutdown_scheduler():
    if scheduler.running:
        scheduler.shutdown()
        logger.info("APScheduler shut down")