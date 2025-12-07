from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo
import asyncio
from unittest.mock import AsyncMock, MagicMock

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pytz import utc

from app.scheduler.job_manager import JobManager
from app.scheduler.scheduler_instance import scheduler as global_scheduler
from app.models.users import User
from app.models.settings import UserSettings


def test_schedule_user_jobs_registers_cron_jobs(monkeypatch):
    # Prepare test scheduler and monkeypatch global scheduler to avoid side effects
    test_scheduler = AsyncIOScheduler(timezone=utc)
    import app.scheduler.job_manager as jm
    monkeypatch.setattr(jm, 'scheduler', test_scheduler)

    # create simple test user and settings (avoid SQLModel instantiation complexities)
    class SimpleUser:
        def __init__(self):
            self.id = 999
            self.tg_user_id = 999
            self.tg_chat_id = 999
            self.user_timezone = 'UTC'
            self.wake_time = time(hour=8, minute=30)
            self.bed_time = time(hour=23, minute=0)

    class SimpleSettings:
        def __init__(self):
            self.user_id = 999
            self.enable_morning_checkin = True
            self.enable_evening_wrapup = True
            self.enable_weekly_plan = False
            self.enable_monthly_plan = False

    user = SimpleUser()
    settings = SimpleSettings()

    JobManager.schedule_user_jobs(user, settings)

    morning_job = test_scheduler.get_job('morning_999')
    assert morning_job is not None
    assert morning_job.trigger is not None
    # next fire time for morning should be at user wake time
    now = datetime.now(timezone.utc)
    next_run = morning_job.trigger.get_next_fire_time(previous_fire_time=None, now=now)
    # ensure next_run is not None and has correct hour/minute in user's local timezone
    assert next_run is not None
    assert next_run.hour == 8 and next_run.minute == 30

    evening_job = test_scheduler.get_job('evening_999')
    assert evening_job is not None
    next_run_evening = evening_job.trigger.get_next_fire_time(previous_fire_time=None, now=now)
    assert next_run_evening is not None
    # evening scheduled 1 hour before 23:00 -> 22:00
    assert next_run_evening.hour == 22 and next_run_evening.minute == 0

    # cleanup
    if test_scheduler.running:
        test_scheduler.shutdown(wait=False)


def test_evening_wrapup_job_calls_flow_when_not_in_break_mode(monkeypatch):
    """evening_wrapup_job should call ProactiveFlows.evening_wrapup"""
    from app.scheduler.jobs import evening_wrapup_job

    fake_session = AsyncMock()
    fake_user = MagicMock(id=123)
    fake_session.get = AsyncMock(return_value=fake_user)
    fake_session.close = AsyncMock()

    monkeypatch.setattr("app.scheduler.jobs.AsyncSessionLocal", lambda: fake_session)
    monkeypatch.setattr("app.scheduler.jobs._is_break_mode_active", AsyncMock(return_value=False))

    flows_mock = AsyncMock()
    monkeypatch.setattr("app.scheduler.jobs.ProactiveFlows", lambda session: flows_mock)

    asyncio.run(evening_wrapup_job(user_id=123))

    flows_mock.evening_wrapup.assert_awaited_once_with(fake_user)
    fake_session.commit.assert_awaited()
