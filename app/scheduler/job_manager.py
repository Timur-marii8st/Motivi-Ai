from __future__ import annotations
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from loguru import logger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from sqlalchemy.ext.asyncio import AsyncSession


from ..models.users import User
from ..models.settings import UserSettings
from .scheduler_instance import scheduler
from ..config import settings as app_settings

class JobManager:
    """
    Manages per-user scheduled jobs.
    """

    USER_JOB_PREFIXES = [
        "morning",
        "evening",
        "weekly",
        "monthly",
        "news_digest",
        "channel_batch",
        "proactive_planner",
        "proactive_planner_refresh",
    ]

    @staticmethod
    def schedule_user_jobs(user: User, settings: UserSettings):
        """
        Schedule or reschedule all jobs for a user based on their timezone and preferences.
        """
        if not user.user_timezone:
            logger.warning("User {} has no timezone; skipping job scheduling", user.id)
            return

        tz = ZoneInfo(user.user_timezone)
        
        # Remove existing deterministic jobs for this user before rescheduling.
        # Legacy morning/evening/weekly/monthly jobs are intentionally removed:
        # smart proactive planning schedules one-off touches instead.
        for prefix in JobManager.USER_JOB_PREFIXES:
            job_id = f"{prefix}_{user.id}"
            if scheduler.get_job(job_id):
                scheduler.remove_job(job_id)
                logger.debug("Removed existing job {} before rescheduling", job_id)
        for job in scheduler.get_jobs():
            if job.id.startswith(f"proactive_touch_{user.id}_"):
                scheduler.remove_job(job.id)
                logger.debug("Removed existing job {} before rescheduling", job.id)

        # Daily smart proactive planner. The LLM decides whether anything should
        # actually be sent today/tomorrow; this cron only gives it a chance to plan.
        planner_job_id = f"proactive_planner_{user.id}"
        if getattr(settings, "enable_smart_proactivity", True):
            planner_time = user.wake_time or getattr(settings, "morning_window_start", None)
            planner_hour = planner_time.hour if planner_time else 9
            planner_minute = planner_time.minute if planner_time else 0
            scheduler.add_job(
                func="app.scheduler.jobs:proactive_planner_job",
                trigger=CronTrigger(hour=planner_hour, minute=planner_minute, timezone=tz),
                id=planner_job_id,
                args=[user.id],
                replace_existing=True,
            )
            logger.info(
                "Scheduled smart proactive planner for user {} at {:02d}:{:02d}",
                user.id,
                planner_hour,
                planner_minute,
            )
        else:
            logger.info("Smart proactive planner not scheduled for user {} (disabled)", user.id)

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

        # Channel batch digest flush (periodic, if channel monitoring is enabled)
        job_id = f"channel_batch_{user.id}"
        if getattr(settings, "enable_channel_monitoring", False):
            flush_hours = app_settings.USERBOT_CHANNEL_BATCH_FLUSH_HOURS
            scheduler.add_job(
                func="app.scheduler.jobs:channel_batch_flush_job",
                trigger=CronTrigger(
                    hour=f"*/{flush_hours}",
                    minute=0,
                    timezone=tz,
                ),
                id=job_id,
                args=[user.id],
                replace_existing=True,
            )
            logger.info(
                "Scheduled channel batch flush for user {} every {}h",
                user.id, flush_hours,
            )
        else:
            logger.info(
                "Channel batch flush not scheduled for user {} (channel monitoring disabled)",
                user.id,
            )

    @staticmethod
    def schedule_planner_refresh(user_id: int, delay_minutes: int = 15) -> None:
        """Schedule a near-future planner run after meaningful user interaction."""
        job_id = f"proactive_planner_refresh_{user_id}"
        run_at = datetime.now(timezone.utc) + timedelta(minutes=delay_minutes)
        scheduler.add_job(
            func="app.scheduler.jobs:proactive_planner_job",
            trigger=DateTrigger(run_date=run_at, timezone=timezone.utc),
            id=job_id,
            args=[user_id],
            replace_existing=True,
        )
        logger.debug("Scheduled proactive planner refresh for user {} at {}", user_id, run_at)

    @staticmethod
    def remove_user_jobs(user_id: int):
        """Remove all jobs for a user."""
        for prefix in JobManager.USER_JOB_PREFIXES:
            job_id = f"{prefix}_{user_id}"
            if scheduler.get_job(job_id):
                scheduler.remove_job(job_id)
                logger.info("Removed job {}", job_id)
        for job in scheduler.get_jobs():
            if job.id.startswith(f"proactive_touch_{user_id}_"):
                scheduler.remove_job(job.id)
                logger.info("Removed job {}", job.id)

    @staticmethod
    async def reschedule_all_user_jobs(session: AsyncSession) -> int:
        """Rebuild per-user jobs on startup and remove legacy fixed proactive jobs."""
        from sqlmodel import select

        result = await session.execute(select(User))
        users = list(result.scalars().all())
        count = 0
        for user in users:
            result = await session.execute(
                select(UserSettings).where(UserSettings.user_id == user.id)
            )
            user_settings = result.scalar_one_or_none()
            if not user_settings:
                continue
            JobManager.schedule_user_jobs(user, user_settings)
            count += 1
        logger.info("Rescheduled jobs for {} user(s)", count)
        return count

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
