from __future__ import annotations
from zoneinfo import ZoneInfo
from loguru import logger
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import AsyncSession


from ..models.users import User
from ..models.settings import UserSettings
from .scheduler_instance import scheduler

class JobManager:
    """
    Manages per-user scheduled jobs: morning, evening, weekly, monthly.
    """

    @staticmethod
    def schedule_user_jobs(user: User, settings: UserSettings):
        """
        Schedule or reschedule all jobs for a user based on their timezone and preferences.
        """
        if not user.timezone:
            logger.warning("User {} has no timezone; skipping job scheduling", user.id)
            return

        tz = ZoneInfo(user.timezone)
        
        # Morning check-in
        if settings.enable_morning_checkin and user.wake_time:
            wake = user.wake_time
            job_id = f"morning_{user.id}"
            
            # Add new
            scheduler.add_job(
                func="app.scheduler.jobs:morning_checkin_job",
                trigger=CronTrigger(hour=wake.hour, minute=wake.minute, timezone=tz),
                id=job_id,
                args=[user.id],
                replace_existing=True,
            )
            logger.info("Scheduled morning check-in for user {} at {}", user.id, wake)

        # Evening wrap-up (1 hour before bed)
        if settings.enable_evening_wrapup and user.bed_time:
            bed = user.bed_time
            evening_hour = (bed.hour - 1) % 24
            job_id = f"evening_{user.id}"
            
            scheduler.add_job(
                func="app.scheduler.jobs:evening_wrapup_job",
                trigger=CronTrigger(hour=evening_hour, minute=bed.minute, timezone=tz),
                id=job_id,
                args=[user.id],
                replace_existing=True,
            )
            logger.info("Scheduled evening wrap-up for user {} at {}:{:02d}", user.id, evening_hour, bed.minute)

        # Weekly plan (Sundays at 18:00 local time)
        if settings.enable_weekly_plan:
            job_id = f"weekly_{user.id}"
            
            scheduler.add_job(
                func="app.scheduler.jobs:weekly_plan_job",
                trigger=CronTrigger(day_of_week='sun', hour=18, minute=0, timezone=tz),
                id=job_id,
                args=[user.id],
                replace_existing=True,
            )
            logger.info("Scheduled weekly plan for user {}", user.id)

        # Monthly plan (1st of month at 18:00 local time)
        if settings.enable_monthly_plan:
            job_id = f"monthly_{user.id}"
            if scheduler.get_job(job_id):
                scheduler.remove_job(job_id)
            
            scheduler.add_job(
                func="app.scheduler.jobs:monthly_plan_job",
                trigger=CronTrigger(day=1, hour=18, minute=0, timezone=tz),
                id=job_id,
                args=[user.id],
                replace_existing=True,
            )
            logger.info("Scheduled monthly plan for user {}", user.id)

    @staticmethod
    async def remove_user_jobs(user_id: int):
        """Remove all jobs for a user."""
        for prefix in ["morning", "evening", "weekly", "monthly"]:
            job_id = f"{prefix}_{user_id}"
            if scheduler.get_job(job_id):
                await scheduler.remove_job(job_id)
                logger.info("Removed job {}", job_id)

    @staticmethod
    async def schedule_habit_reminders(session: AsyncSession, user_id: int):
        """
        Schedule daily reminders for user's active habits with reminder_time set.
        """
        from ..services.habit_service import HabitService
        from ..models.users import User
        
        user = await session.get(User, user_id)
        if not user or not user.timezone:
            return
        
        habits = await HabitService.list_habits(session, user_id, active_only=True)
        
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(user.timezone)
        
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