from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock

from app.models.calendar_event import CalendarEvent  # noqa: F401
from app.services.calendar_service import CalendarService


def _install_fake_scheduler(monkeypatch) -> MagicMock:
    """Inject a fake scheduler so reminder jobs never touch the real job store."""
    fake_scheduler = MagicMock()
    fake_scheduler.get_job.return_value = None
    module = ModuleType("app.scheduler.scheduler_instance")
    module.scheduler = fake_scheduler
    monkeypatch.setitem(sys.modules, "app.scheduler.scheduler_instance", module)
    return fake_scheduler


class _ScalarResult:
    def __init__(self, value=None):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _Scalars:
    def __init__(self, values):
        self._values = values

    def all(self):
        return self._values


class _ListResult:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return _Scalars(self._values)


class _FakeSession:
    def __init__(self, execute_result=None, get_result=None):
        result = (
            _ListResult(execute_result)
            if isinstance(execute_result, list)
            else _ScalarResult(execute_result)
        )
        self.execute = MagicMock(return_value=result)
        self.get = MagicMock(return_value=get_result)
        self.flush = MagicMock()
        self.added = []

    def add(self, item):
        self.added.append(item)


async def _await(value):
    return value


def _fake_async_session(session: _FakeSession) -> _FakeSession:
    """Wrap sync fakes so `await session.execute(...)` works."""

    session.execute = AsyncMock(return_value=session.execute.return_value)
    session.flush = AsyncMock()
    session.get = AsyncMock(return_value=session.get.return_value)
    return session


def test_create_event_rejects_past_events(monkeypatch):
    monkeypatch.setattr(CalendarService, "schedule_reminder", MagicMock())
    session = _fake_async_session(_FakeSession(execute_result=[]))

    event = asyncio.run(
        CalendarService.create_event(
            session,
            user_id=1,
            title="Прошедшая встреча",
            starts_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
    )

    assert event is None
    assert session.added == []


def test_create_event_deduplicates_same_source_message(monkeypatch):
    monkeypatch.setattr(CalendarService, "schedule_reminder", MagicMock())
    existing = CalendarEvent(
        id=7,
        user_id=1,
        title="Созвон с Алексом",
        starts_at=datetime.now(timezone.utc) + timedelta(days=1),
        status="active",
        source_chat_id=100,
        source_message_id=10,
    )
    session = _fake_async_session(_FakeSession(execute_result=[existing]))

    event = asyncio.run(
        CalendarService.create_event(
            session,
            user_id=1,
            title="Созвон с Алексом",
            starts_at=datetime.now(timezone.utc) + timedelta(days=2),
            source_type="dm",
            source_chat_id=100,
            source_message_id=10,
        )
    )

    assert event is None


def test_create_event_stores_fields_and_schedules_reminder(monkeypatch):
    schedule = MagicMock(return_value="calendar_reminder_1")
    monkeypatch.setattr(CalendarService, "schedule_reminder", schedule)
    session = _fake_async_session(_FakeSession(execute_result=[]))
    starts_at = datetime.now(timezone.utc) + timedelta(days=1)

    event = asyncio.run(
        CalendarService.create_event(
            session,
            user_id=1,
            title="  Дедлайн отчёта  ",
            starts_at=starts_at,
            description="квартальный отчёт",
            source_type="channel",
            source_name="Рабочий канал",
            source_chat_id=100,
            source_message_id=10,
        )
    )

    assert event is not None
    assert event.title == "Дедлайн отчёта"
    assert event.source_type == "channel"
    assert event.reminder_job_id == "calendar_reminder_1"
    assert session.added[-1] is event
    schedule.assert_called_once_with(event)


def test_postpone_shifts_event_and_reschedules(monkeypatch):
    fake_scheduler = _install_fake_scheduler(monkeypatch)

    starts_at = datetime.now(timezone.utc) + timedelta(days=1)
    event = CalendarEvent(
        id=42,
        user_id=1,
        title="Встреча",
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=1),
        status="active",
        remind_before_minutes=15,
    )
    session = _fake_async_session(_FakeSession(get_result=event))

    postponed = asyncio.run(CalendarService.postpone(session, 42, 1, 60))

    assert postponed is event
    assert event.starts_at == starts_at + timedelta(hours=1)
    assert event.ends_at == starts_at + timedelta(hours=2)
    assert event.reminder_job_id == "calendar_reminder_42"
    fake_scheduler.add_job.assert_called_once()


def test_set_status_cancels_event_and_removes_reminder(monkeypatch):
    fake_scheduler = _install_fake_scheduler(monkeypatch)
    fake_scheduler.get_job.return_value = MagicMock()  # pretend the job exists

    event = CalendarEvent(
        id=42,
        user_id=1,
        title="Встреча",
        starts_at=datetime.now(timezone.utc) + timedelta(days=1),
        status="active",
        reminder_job_id="calendar_reminder_42",
    )
    session = _fake_async_session(_FakeSession(get_result=event))

    result = asyncio.run(CalendarService.set_status(session, 42, 1, "cancelled"))

    assert result is event
    assert event.status == "cancelled"
    assert event.reminder_job_id is None
    fake_scheduler.remove_job.assert_called_once_with("calendar_reminder_42")


def test_set_status_rejects_other_users_events(monkeypatch):
    monkeypatch.setattr(CalendarService, "remove_reminder", MagicMock())
    event = CalendarEvent(
        id=42,
        user_id=2,
        title="Чужое событие",
        starts_at=datetime.now(timezone.utc) + timedelta(days=1),
        status="active",
    )
    session = _fake_async_session(_FakeSession(get_result=event))

    result = asyncio.run(CalendarService.set_status(session, 42, 1, "cancelled"))

    assert result is None
    assert event.status == "active"
