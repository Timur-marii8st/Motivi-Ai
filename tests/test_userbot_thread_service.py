from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

from app.models.core_memory import CoreMemory  # noqa: F401
from app.models.episode import Episode, EpisodeEmbedding  # noqa: F401
from app.models.habit import Habit, HabitLog  # noqa: F401
from app.models.oauth_token import OAuthToken  # noqa: F401
from app.models.payment import Payment  # noqa: F401
from app.models.plan import Plan  # noqa: F401
from app.models.profile_completeness import ProfileCompleteness  # noqa: F401
from app.models.settings import UserSettings  # noqa: F401
from app.models.userbot_thread import UserBotThread
from app.models.user_trigger import UserTrigger  # noqa: F401
from app.models.working_memory import WorkingMemory  # noqa: F401
from app.services.userbot_thread_service import UserBotThreadService


class _ScalarResult:
    def __init__(self, value=None):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeSession:
    def __init__(self, execute_result=None, get_result=None):
        self.execute = AsyncMock(return_value=_ScalarResult(execute_result))
        self.get = AsyncMock(return_value=get_result)
        self.flush = AsyncMock()
        self.added = []

    def add(self, item):
        self.added.append(item)


def test_create_or_update_incoming_persists_summary_without_raw_text():
    service = UserBotThreadService()
    session = _FakeSession()

    thread = asyncio.run(
        service.create_or_update_incoming(
            session,
            user_id=1,
            chat_id=100,
            chat_type="dm",
            sender_tg_id=200,
            sender_name="Alex",
            message_id=10,
            message_text="raw sensitive message body",
            suggested_replies=["ok", "later"],
            classification={
                "requires_response": True,
                "importance": 4,
                "suggested_followup_at": datetime.now(timezone.utc).isoformat(),
                "memory_worthy": False,
                "memory_items": ["Alex prefers short replies"],
                "message_summary": "Alex asked for a reply.",
            },
        )
    )

    assert thread.message_text is None
    assert thread.message_summary == "Alex asked for a reply."
    assert thread.status == "open"
    assert thread.importance == 4
    assert thread.suggested_replies_json == ["ok", "later"]
    assert session.added == [thread]
    session.flush.assert_awaited_once()


def test_mark_replied_closes_only_owned_thread():
    service = UserBotThreadService()
    thread = UserBotThread(user_id=1, chat_id=100, status="open")
    session = _FakeSession(get_result=thread)

    result = asyncio.run(service.mark_replied(session, user_id=1, thread_id=42))

    assert result is True
    assert thread.status == "replied"
    assert thread.last_outgoing_at is not None
    assert session.added == [thread]


def test_user_followup_max_zero_blocks_reminders(monkeypatch):
    service = UserBotThreadService()
    settings = type(
        "Settings",
        (),
        {
            "enable_userbot_followups": True,
            "userbot_followup_max_per_day": 0,
        },
    )()
    monkeypatch.setattr(service, "_get_user_settings", AsyncMock(return_value=settings))
    monkeypatch.setattr(service, "_get_followup_counter", AsyncMock(return_value=0))

    allowed = asyncio.run(service._can_send_followup(_FakeSession(), user_id=1))

    assert allowed is False
