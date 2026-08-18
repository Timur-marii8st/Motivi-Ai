from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.services import userbot_monitor
from app.services.calendar_service import CalendarExtractionService, parse_iso_to_utc


class _Event:
    def __init__(
        self,
        *,
        chat_id: int,
        sender_id: int | None = None,
        is_private: bool = True,
        out: bool = False,
        text: str = "hello",
    ):
        self.chat_id = chat_id
        self.sender_id = sender_id
        self.is_private = is_private
        self.out = out
        self.message = SimpleNamespace(message=text, sender_id=sender_id, out=out)


def test_assistant_bot_incoming_events_are_ignored():
    assert userbot_monitor._should_ignore_assistant_bot_event(
        _Event(chat_id=123, sender_id=777),
        assistant_bot_id=777,
    )
    assert userbot_monitor._should_ignore_assistant_bot_event(
        _Event(chat_id=777, sender_id=555),
        assistant_bot_id=777,
    )
    assert not userbot_monitor._should_ignore_assistant_bot_event(
        _Event(chat_id=123, sender_id=555),
        assistant_bot_id=777,
    )


def test_outgoing_private_messages_to_assistant_bot_are_skipped(monkeypatch):
    monkeypatch.setattr(
        userbot_monitor,
        "_get_redis",
        AsyncMock(side_effect=AssertionError("redis should not be touched")),
    )

    asyncio.run(
        userbot_monitor._handle_outgoing_message(
            _Event(chat_id=777, sender_id=123, is_private=True, out=True),
            user_id=1,
            assistant_bot_id=777,
        )
    )


def test_reply_batch_text_groups_multiple_messages():
    text = userbot_monitor._batch_message_text(
        [
            {"message_id": 10, "text": "first thought"},
            {"message_id": 11, "text": "and one more detail"},
        ]
    )

    assert text == "1. first thought\n2. and one more detail"
    assert (
        userbot_monitor._latest_batch_message_id(
            [{"message_id": 10}, {"message_id": 11}],
            fallback=9,
        )
        == 11
    )


def test_check_if_message_read_uses_live_dialog_cursor(monkeypatch):
    cache_read = AsyncMock()
    get_live_cursor = AsyncMock(return_value=15)

    monkeypatch.setattr(
        userbot_monitor,
        "get_cached_read_marker",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(userbot_monitor, "get_read_inbox_max_id", get_live_cursor)
    monkeypatch.setattr(userbot_monitor, "cache_read_marker", cache_read)

    is_read = asyncio.run(
        userbot_monitor._check_if_message_read(
            client=object(),
            user_id=1,
            chat_id=100,
            message_id=10,
        )
    )

    assert is_read is True
    get_live_cursor.assert_awaited_once()
    cache_read.assert_awaited_once_with(1, 100, 15)


def test_classification_requires_response_normalizes_string_false():
    assert not userbot_monitor._classification_requires_response({})
    assert not userbot_monitor._classification_requires_response(
        {"requires_response": "false"}
    )
    assert not userbot_monitor._classification_requires_response(
        {"requires_response": "нет"}
    )
    assert userbot_monitor._classification_requires_response(
        {"requires_response": "yes"}
    )


def test_unavailable_classification_fails_closed():
    classification = {
        "classification_available": False,
        "requires_response": False,
        "importance": 1,
    }

    assert not userbot_monitor._classification_available(classification)
    assert not userbot_monitor._classification_requires_response(classification)


def test_classification_importance_is_clamped():
    assert userbot_monitor._classification_importance({}) == 1
    assert userbot_monitor._classification_importance({"importance": 9}) == 5
    assert userbot_monitor._classification_importance({"importance": "3"}) == 3
    assert userbot_monitor._classification_importance({"importance": "bad"}) == 1


def test_format_calendar_lines_renders_added_events(monkeypatch):
    monkeypatch.setattr(
        userbot_monitor, "_get_user_timezone", AsyncMock(return_value="UTC")
    )
    event = SimpleNamespace(
        title="Встреча с Алексом",
        starts_at=datetime(2026, 8, 20, 15, 0, tzinfo=timezone.utc),
    )

    lines = asyncio.run(userbot_monitor._format_calendar_lines(1, [event]))

    assert "Добавила в календарь" in lines
    assert "Встреча с Алексом" in lines
    assert "20.08 15:00" in lines
    assert asyncio.run(userbot_monitor._format_calendar_lines(1, [])) == ""


def test_parse_iso_to_utc_handles_naive_local_and_invalid():
    aware = parse_iso_to_utc("2026-08-20T15:00:00+03:00", "UTC")
    assert aware == datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)

    naive = parse_iso_to_utc("2026-08-20T15:00:00", "Etc/GMT-3")
    assert naive == datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)

    assert parse_iso_to_utc("", "UTC") is None
    assert parse_iso_to_utc("not-a-date", "UTC") is None


def test_extraction_sanitizes_events_and_skips_past():
    service = CalendarExtractionService()
    future = datetime.now(timezone.utc) + timedelta(days=1)
    past = datetime.now(timezone.utc) - timedelta(days=1)

    events = service._sanitize_events(
        {
            "events": [
                {
                    "title": "Созвон с командой",
                    "starts_at_iso": future.strftime("%Y-%m-%dT%H:%M:%S"),
                    "ends_at_iso": None,
                    "all_day": False,
                    "remind_before_minutes": 30,
                },
                {
                    "title": "Старый дедлайн",
                    "starts_at_iso": past.strftime("%Y-%m-%dT%H:%M:%S"),
                },
                {"title": "", "starts_at_iso": "garbage"},
            ]
        },
        "UTC",
    )

    assert len(events) == 1
    assert events[0]["title"] == "Созвон с командой"
    assert events[0]["remind_before_minutes"] == 30
    assert events[0]["starts_at"].tzinfo is not None


def test_extraction_caps_event_count():
    service = CalendarExtractionService()
    future = datetime.now(timezone.utc) + timedelta(days=1)
    payload = {
        "events": [
            {
                "title": f"Event {i}",
                "starts_at_iso": future.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            for i in range(10)
        ]
    }

    events = service._sanitize_events(payload, "UTC")
    assert len(events) == 3
