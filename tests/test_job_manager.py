from datetime import datetime, time, timezone
import asyncio
from unittest.mock import AsyncMock, MagicMock

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pytz import utc

from app.scheduler.job_manager import JobManager


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
            self.enable_smart_proactivity = True
            self.enable_news_digest = False
            self.enable_channel_monitoring = False

    user = SimpleUser()
    settings = SimpleSettings()

    JobManager.schedule_user_jobs(user, settings)

    planner_job = test_scheduler.get_job('proactive_planner_999')
    assert planner_job is not None
    assert planner_job.trigger is not None
    # Planner runs at wake time, but the planner LLM decides whether to send anything.
    now = datetime.now(timezone.utc)
    next_run = planner_job.trigger.get_next_fire_time(previous_fire_time=None, now=now)
    # ensure next_run is not None and has correct hour/minute in user's local timezone
    assert next_run is not None
    assert next_run.hour == 8 and next_run.minute == 30

    assert test_scheduler.get_job('morning_999') is None
    assert test_scheduler.get_job('evening_999') is None
    assert test_scheduler.get_job('weekly_999') is None
    assert test_scheduler.get_job('monthly_999') is None

    # cleanup
    if test_scheduler.running:
        test_scheduler.shutdown(wait=False)


def test_proactive_touch_job_calls_generic_flow_when_not_in_break_mode(monkeypatch):
    """proactive_touch_job should call ProactiveFlows._run_flow"""
    from app.scheduler.jobs import proactive_touch_job

    fake_session = AsyncMock()
    fake_user = MagicMock(id=123)
    fake_session.get = AsyncMock(return_value=fake_user)
    fake_session.close = AsyncMock()

    monkeypatch.setattr("app.scheduler.jobs.AsyncSessionLocal", lambda: fake_session)
    monkeypatch.setattr("app.scheduler.jobs._is_break_mode_active", AsyncMock(return_value=False))
    monkeypatch.setattr("app.scheduler.jobs.get_bot_instance", lambda: MagicMock())

    flows_mock = AsyncMock()
    monkeypatch.setattr("app.scheduler.jobs.ProactiveFlows", lambda session, bot=None: flows_mock)

    asyncio.run(proactive_touch_job(user_id=123, touch_type="reflection", prompt="Ask for a short reflection", reason="test"))

    flows_mock._run_flow.assert_awaited_once()
    fake_session.commit.assert_awaited()
