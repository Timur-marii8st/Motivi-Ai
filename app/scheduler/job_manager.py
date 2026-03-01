from __future__ import annotations
from zoneinfo import ZoneInfo
from loguru import logger
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import AsyncSession


from ..models.users import User
from ..models.settings import UserSettings
from .scheduler_instance import scheduler
from ..config import settings as app_settings

class JobManager:
    """
    Manages per-user scheduled jobs: morning, evening, weekly, monthly.
    """

    @staticmethod
    def schedule_user_jobs(user: User, settings: UserSettings):
        """
        Schedule or reschedule all jobs for a user based on their timezone and preferences.
        """
        if not user.user_timezone:
            logger.warning("User {} has no timezone; skipping job scheduling", user.id)
            return

        tz = ZoneInfo(user.user_timezone)
        
        # Remove all existing jobs for this user first to avoid conflicts
        for prefix in ["morning", "evening", "weekly", "monthly", "news_digest"]:
            job_id = f"{prefix}_{user.id}"
            if scheduler.get_job(job_id):
                scheduler.remove_job(job_id)
                logger.debug("Removed existing job {} before rescheduling", job_id)
        
        # Morning check-in
        job_id = f"morning_{user.id}"
        if settings.enable_morning_checkin and user.wake_time:
            wake = user.wake_time
            scheduler.add_job(
                func="app.scheduler.jobs:morning_checkin_job",
                trigger=CronTrigger(hour=wake.hour, minute=wake.minute, timezone=tz),
                id=job_id,
                args=[user.id],
                replace_existing=True,
            )
            logger.info("Scheduled morning check-in for user {} at {}", user.id, wake)
        else:
            logger.info("Morning check-in not scheduled for user {} (disabled or wake_time not set)", user.id)

        # Evening wrap-up (1 hour before bed)
        job_id = f"evening_{user.id}"
        if settings.enable_evening_wrapup and user.bed_time:
            bed = user.bed_time
            # Calculate 1 hour before bed time, handling midnight rollover
            if bed.hour == 0:
                evening_hour = 23
            else:
                evening_hour = bed.hour - 1
            scheduler.add_job(
                func="app.scheduler.jobs:evening_wrapup_job",
                trigger=CronTrigger(hour=evening_hour, minute=bed.minute, timezone=tz),
                id=job_id,
                args=[user.id],
                replace_existing=True,
            )
            logger.info("Scheduled evening wrap-up for user {} at {}:{:02d} (1 hour before bed at {}:{:02d})", 
                       user.id, evening_hour, bed.minute, bed.hour, bed.minute)
        else:
            logger.info("Evening wrap-up not scheduled for user {} (disabled or bed_time not set)", user.id)

        # Weekly plan (Sundays at 18:00 local time)
        job_id = f"weekly_{user.id}"
        if settings.enable_weekly_plan:
            scheduler.add_job(
                func="app.scheduler.jobs:weekly_plan_job",
                trigger=CronTrigger(day_of_week='sun', hour=18, minute=0, timezone=tz),
                id=job_id,
                args=[user.id],
                replace_existing=True,
            )
            logger.info("Scheduled weekly plan for user {}", user.id)
        else:
            logger.info("Weekly plan not scheduled for user {} (disabled)", user.id)

        # Monthly plan (1st of month at 18:00 local time)
        job_id = f"monthly_{user.id}"
        if settings.enable_monthly_plan:
            scheduler.add_job(
                func="app.scheduler.jobs:monthly_plan_job",
                trigger=CronTrigger(day=1, hour=18, minute=0, timezone=tz),
                id=job_id,
                args=[user.id],
                replace_existing=True,
            )
            logger.info("Scheduled monthly plan for user {}", user.id)
        else:
            logger.info("Monthly plan not scheduled for user {} (disabled)", user.id)

        # News digest (wake_time + NEWS_DIGEST_OFFSET_MINUTES, if enabled and wake_time is set)
        job_id = f"news_digest_{user.id}"
        if settings.enable_news_digest and user.wake_time:
            from datetime import datetime, timedelta

            wake_dt = datetime.combine(datetime.today(), user.wake_time)
            digest_dt = wake_dt + timedelta(
                minutes=app_settings.NEWS_DIGEST_OFFSET_MINUTES
            )
            scheduler.add_job(
                func="app.scheduler.jobs:news_digest_job",
                trigger=CronTrigger(
                    hour=digest_dt.hour,
                    minute=digest_dt.minute,
                    timezone=tz,
                ),
                id=job_id,
                args=[user.id],
                replace_existing=True,
            )
            logger.info(
                "Scheduled news digest for user {} at {:02d}:{:02d} ({}m after wake at {})",
                user.id,
                digest_dt.hour,
                digest_dt.minute,
                app_settings.NEWS_DIGEST_OFFSET_MINUTES,
                user.wake_time,
            )
        else:
            logger.info(
                "News digest not scheduled for user {} (disabled or wake_time not set)",
                user.id,
            )

    @staticmethod
    async def remove_user_jobs(user_id: int):
        """Remove all jobs for a user."""
        for prefix in ["morning", "evening", "weekly", "monthly", "news_digest"]:
            job_id = f"{prefix}_{user_id}"
            if scheduler.get_job(job_id):
                scheduler.remove_job(job_id)
                logger.info("Removed job {}", job_id)

    @staticmethod
    async def schedule_user_triggers(session: AsyncSession, user: User):
        """Schedule or reschedule all active custom triggers for a user."""
        from ..models.user_trigger import UserTrigger
        from sqlmodel import select

        if not user.user_timezone:
            logger.warning("User {} has no timezone; skipping trigger scheduling", user.id)
            return

        tz = ZoneInfo(user.user_timezone)

        # Remove all existing trigger jobs for this user
        for job in scheduler.get_jobs():
            if job.id.startswith(f"trigger_{user.id}_"):
                scheduler.remove_job(job.id)

        # Schedule active triggers
        result = await session.execute(
            select(UserTrigger).where(
                UserTrigger.user_id == user.id,
                UserTrigger.active == True,  # noqa: E712
            )
        )
        triggers = list(result.scalars().all())

        for trigger in triggers:
            job_id = f"trigger_{user.id}_{trigger.id}"
            cron_kwargs: dict = dict(
                hour=trigger.cron_hour,
                minute=trigger.cron_minute,
                timezone=tz,
            )
            if trigger.cron_weekdays:
                cron_kwargs["day_of_week"] = trigger.cron_weekdays

            scheduler.add_job(
                func="app.scheduler.jobs:custom_trigger_job",
                trigger=CronTrigger(**cron_kwargs),
                id=job_id,
                args=[user.id, trigger.id],
                replace_existing=True,
            )
            logger.info(
                "Scheduled custom trigger {} for user {} at {:02d}:{:02d}",
                trigger.id, user.id, trigger.cron_hour, trigger.cron_minute,
            )

    @staticmethod
    async def schedule_habit_reminders(session: AsyncSession, user_id: int):
        """
        Schedule daily reminders for user's active habits with reminder_time set.
        """
        from ..services.habit_service import HabitService
        from ..models.users import User
        
        user = await session.get(User, user_id)
        if not user or not user.user_timezone:
            return
        
        habits = await HabitService.list_habits(session, user_id, active_only=True)
        
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(user.user_timezone)
        
        for habit in habits:
            if habit.reminder_enabled and habit.reminder_time:
                job_id = f"habit_reminder_{habit.id}"
                
                if scheduler.get_job(job_id):
                    scheduler.remove_job(job_id)
                
                scheduler.add_job(
                    func="app.scheduler.jobs:habit_reminder_job",
                    trigger=CronTrigger(
                        hour=habit.reminder_time.hour,
                        minute=habit.reminder_time.minute,
                        timezone=tz
                    ),
                    id=job_id,
                    args=[habit.id],
                    replace_existing=True,
                )
                logger.info("Scheduled reminder for habit {} at {}", habit.id, habit.reminder_time)