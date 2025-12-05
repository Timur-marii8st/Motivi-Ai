import asyncio
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timedelta, timezone

from app.services.tool_executor import ToolExecutor
from app.scheduler.scheduler_instance import scheduler, start_scheduler, shutdown_scheduler
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pytz import utc


def test_schedule_list_and_cancel_reminder(monkeypatch):
    """Test that ToolExecutor can schedule a reminder, list it, and cancel it."""
    fake_session = AsyncMock()
    fake_mcp = MagicMock()

    tool_executor = ToolExecutor(fake_session, fake_mcp)

    # Do not start scheduler in test; we'll just use jobstore and scheduler utilities

    # Use user's timezone if not provided (simulate user in Europe/Moscow = UTC+3)
    # We'll schedule for 2 minutes from now in user's timezone
    user_tz = "Europe/Moscow"
    # Compute local 'now' in user's timezone and then schedule 2 minutes later
    from zoneinfo import ZoneInfo
    now_local = datetime.now(timezone.utc).astimezone(ZoneInfo(user_tz))
    run_dt_local = now_local + timedelta(minutes=2)
    run_dt = run_dt_local.replace(tzinfo=None)
    args = {
        "message_text": "Reminder from test",
        "reminder_datetime_iso": run_dt.isoformat(),
    }

    # Simulate user timezone in DB
    class FakeUser:
        def __init__(self):
            self.user_timezone = user_tz

    async def _fake_get(model, pk):
        return FakeUser()

    fake_session.get = AsyncMock(side_effect=_fake_get)

    result = asyncio.run(tool_executor._schedule_reminder(args, chat_id=42, user_id=123))
    assert result["success"] is True
    job_id = result["job_id"]
    assert result.get("scheduled_for_utc") is not None
    assert result.get("timezone") is not None

    # Job should be present in scheduler
    job = scheduler.get_job(job_id)
    assert job is not None

    # Verify scheduled run_date converted from local timezone to UTC
    expected_utc = run_dt_local.astimezone(timezone.utc)
    actual_run = job.trigger.run_date
    # Should be very close (less than 2 seconds difference)
    assert abs((actual_run - expected_utc).total_seconds()) < 2

    # List reminders should show our job
    listed = asyncio.run(tool_executor._list_reminders(user_id=123))
    assert listed["success"] is True
    assert listed["count"] >= 1
    # find job in list
    assert any(r["job_id"] == job_id for r in listed["reminders"]) if listed["count"] > 0 else False

    # Cancel the reminder
    cancel_result = asyncio.run(tool_executor._cancel_reminder({"job_id": job_id}, user_id=123))
    assert cancel_result["success"] is True

    # After cancellation job should be gone
    assert scheduler.get_job(job_id) is None


def test_schedule_reminder_in_past_is_rejected():
    fake_session = AsyncMock()
    fake_mcp = MagicMock()
    tool_executor = ToolExecutor(fake_session, fake_mcp)

    # Do not start scheduler in test; we'll just use jobstore and scheduler utilities

    past_dt = datetime.now(timezone.utc) - timedelta(minutes=5)
    args = {
        "message_text": "Past reminder",
        "reminder_datetime_iso": past_dt.isoformat(),
    }

    result = asyncio.run(tool_executor._schedule_reminder(args, chat_id=42, user_id=123))
    assert result["success"] is False
    assert "past" in result["error"].lower()


def test_schedule_with_explicit_timezone_works():
    fake_session = AsyncMock()
    fake_mcp = MagicMock()
    tool_executor = ToolExecutor(fake_session, fake_mcp)

    # Choose a timezone and schedule a naive datetime but provide timezone explicitly
    user_tz = 'Europe/London'  # UTC or UTC+0 for simplicity
    from zoneinfo import ZoneInfo
    now_local = datetime.now(timezone.utc).astimezone(ZoneInfo(user_tz))
    run_dt_local = now_local + timedelta(minutes=2)
    run_dt_naive = run_dt_local.replace(tzinfo=None)

    args = {
        'message_text': 'Timezone explicit test',
        'reminder_datetime_iso': run_dt_naive.isoformat(),
        'timezone': user_tz
    }

    result = asyncio.run(tool_executor._schedule_reminder(args, chat_id=123, user_id=321))
    assert result['success'] is True
    job = scheduler.get_job(result['job_id'])
    expected_utc = run_dt_local.astimezone(timezone.utc)
    actual_run = job.trigger.run_date
    assert abs((actual_run - expected_utc).total_seconds()) < 2


def test_scheduler_job_runs_async(monkeypatch):
    """Start an in-memory scheduler and verify a scheduled job fires and calls send_message."""
    # We'll run an async helper inside asyncio.run to properly start the scheduler
    async def run_test():
        fake_session = AsyncMock()
        fake_mcp = MagicMock()
        tool_executor = ToolExecutor(fake_session, fake_mcp)

        test_scheduler = AsyncIOScheduler(timezone=utc)
        test_scheduler.start()

        # Monkeypatch the global scheduler to our test scheduler
        import app.scheduler.scheduler_instance as inst
        monkeypatch.setattr(inst, 'scheduler', test_scheduler)

        # Setup fake bot to capture send_message
        event = asyncio.Event()
        async def fake_send_message(chat_id, message):
            event.set()

        class FakeBot:
            def __init__(self, *_, **__):
                self.send_message = fake_send_message

        monkeypatch.setattr('aiogram.Bot', FakeBot)
        # Prevent DB queries inside job by monkeypatching AsyncSessionLocal and break mode checker
        fake_session_for_job = AsyncMock()
        class FakeUserSmall:
            def __init__(self):
                self.id = 999
                self.tg_chat_id = 42

        async def fake_get(model, pk):
            return FakeUserSmall()

        fake_session_for_job.get = AsyncMock(side_effect=fake_get)
        fake_session_for_job.close = AsyncMock()

        monkeypatch.setattr('app.scheduler.jobs.AsyncSessionLocal', lambda: fake_session_for_job)
        monkeypatch.setattr('app.scheduler.jobs._is_break_mode_active', AsyncMock(return_value=False))

        # Set a short-run job 3 seconds from now
        user_tz = 'UTC'
        run_dt = datetime.now(timezone.utc) + timedelta(seconds=3)
        args = {
            'message_text': 'Async test reminder',
            'reminder_datetime_iso': run_dt.isoformat(),
            'timezone': 'UTC'
        }

        result = await tool_executor._schedule_reminder(args, chat_id=42, user_id=999)
        assert result['success'] is True

        # Wait for job execution
        try:
            await asyncio.wait_for(event.wait(), timeout=10)
        finally:
            # Ensure to stop scheduler
            test_scheduler.shutdown(wait=False)

    asyncio.run(run_test())
