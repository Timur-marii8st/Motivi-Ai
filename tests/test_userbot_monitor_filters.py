from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.bot.routers import userbot as userbot_router
from app.services import userbot_monitor


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


class _Bot:
    async def get_me(self):
        return SimpleNamespace(id=777)


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


def test_stale_pending_reply_to_assistant_bot_is_blocked():
    assert asyncio.run(userbot_router._is_reply_target_assistant_bot(777, _Bot()))
    assert not asyncio.run(userbot_router._is_reply_target_assistant_bot(778, _Bot()))


def test_action_plan_sanitizes_only_allowlisted_contact_targets():
    plan = userbot_monitor._sanitize_action_plan(
        {
            "should_propose": True,
            "steps": [
                {
                    "type": "send_message_to_contact",
                    "target_ref": "contact_1",
                    "text": "Please send the latest price.",
                },
                {
                    "type": "send_message_to_contact",
                    "target_ref": "unknown",
                    "target_name": "Lena",
                    "text": "Can you confirm the date?",
                },
            ],
        },
        [{"ref": "contact_1", "label": "Alex", "chat_id": 123}],
    )

    assert plan is not None
    assert plan["steps"][0]["type"] == "send_message_to_contact"
    assert plan["steps"][0]["target_chat_id"] == 123
    assert plan["steps"][0]["requires_separate_approval"] is True
    assert plan["steps"][1]["type"] == "ask_user_clarification"
    assert "Lena" in plan["steps"][1]["question"]


def test_action_plan_keyboard_excludes_completed_steps():
    keyboard = userbot_monitor.build_userbot_approval_keyboard(
        "abc123",
        2,
        action_plan={
            "steps": [
                {"type": "send_message_to_contact", "text": "hi", "status": "pending"},
                {"type": "reply_to_sender", "text": "done", "status": "done"},
                {"type": "ask_user_clarification", "question": "who?", "status": "pending"},
            ],
        },
    )
    callback_data = [
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data
    ]

    assert "ub_plan_step:abc123:0" in callback_data
    assert "ub_plan_edit:abc123:0" in callback_data
    assert "ub_plan_step:abc123:1" not in callback_data
    assert "ub_plan_step:abc123:2" not in callback_data


def test_reply_batch_text_groups_multiple_messages():
    text = userbot_monitor._batch_message_text(
        [
            {"message_id": 10, "text": "first thought"},
            {"message_id": 11, "text": "and one more detail"},
        ]
    )

    assert text == "1. first thought\n2. and one more detail"
    assert userbot_monitor._latest_batch_message_id(
        [{"message_id": 10}, {"message_id": 11}],
        fallback=9,
    ) == 11


def test_auto_reminder_steps_are_hidden_after_execution(monkeypatch):
    calls = []

    async def fake_run_auto_reminder_step(**kwargs):
        calls.append(kwargs["step"])
        return True, "reminder_1_abc"

    monkeypatch.setattr(
        userbot_monitor,
        "_run_auto_reminder_step",
        fake_run_auto_reminder_step,
    )
    reminder_step = {
        "type": "create_reminder",
        "message_text": "Ask Alex about the invoice",
        "reminder_datetime_iso": "2026-06-02T10:00:00+03:00",
        "status": "pending",
    }
    contact_step = {
        "type": "send_message_to_contact",
        "text": "Please confirm the invoice.",
        "status": "pending",
    }

    visible_plan = asyncio.run(
        userbot_monitor._auto_run_and_hide_reminder_steps(
            user_id=1,
            source_chat_id=100,
            sender_tg_id=200,
            owner_tg_chat_id=300,
            action_plan={"steps": [reminder_step, contact_step]},
            bot=_Bot(),
        )
    )

    assert calls == [reminder_step]
    assert reminder_step["status"] == "done"
    assert reminder_step["job_id"] == "reminder_1_abc"
    assert visible_plan == {"steps": [contact_step]}

    reminder_only_plan = asyncio.run(
        userbot_monitor._auto_run_and_hide_reminder_steps(
            user_id=1,
            source_chat_id=100,
            sender_tg_id=200,
            owner_tg_chat_id=300,
            action_plan={"steps": [reminder_step]},
            bot=_Bot(),
        )
    )
    assert reminder_only_plan is None


def test_contact_action_step_sends_only_after_callback(monkeypatch):
    monkeypatch.setattr(
        userbot_router,
        "_is_reply_target_assistant_bot",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        userbot_router,
        "check_reply_rate_limit",
        AsyncMock(return_value=True),
    )
    send_message = AsyncMock(return_value=True)
    monkeypatch.setattr(
        userbot_router,
        "_send_message_with_human_simulation",
        send_message,
    )
    increment = AsyncMock()
    monkeypatch.setattr(userbot_router, "increment_reply_counter", increment)

    step = {
        "type": "send_message_to_contact",
        "target_chat_id": 456,
        "target_label": "Alex",
        "text": "Please confirm the price.",
        "status": "pending",
    }
    ok, message = asyncio.run(
        userbot_router._run_send_message_to_contact_step(
            user_id=1,
            step=step,
            bot=_Bot(),
        )
    )

    assert ok is True
    assert "Alex" in message
    assert step["status"] == "done"
    send_message.assert_awaited_once_with(
        user_id=1,
        chat_id=456,
        text="Please confirm the price.",
    )
    increment.assert_awaited_once_with(1)
