from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from loguru import logger
from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ..config import settings as app_settings
from ..llm.client import async_client
from ..models.settings import UserSettings


OPEN_STATUSES = ("open", "reminded")
CLOSED_STATUSES = ("replied", "dismissed", "closed")


class UserBotThreadService:
    """Persistent state for userbot DM/group notifications.

    Tracks which incoming messages were surfaced to the user so notifications
    can be cleaned up once the user reads or answers the conversation, and
    feeds memory-worthy items into the memory pipeline. Follow-up deadlines
    detected by the classifier are turned into calendar events by the monitor.
    """

    def __init__(self) -> None:
        self.client = async_client
        self.model = app_settings.EXTRACTOR_MODEL_ID

    @staticmethod
    def _thread_model():
        from ..models.userbot_thread import UserBotThread

        return UserBotThread

    async def classify_message(
        self,
        *,
        message_text: str,
        sender_name: str,
        chat_type: str,
        conversation_summary: str | None = None,
    ) -> dict[str, Any]:
        fallback = {
            "classification_available": False,
            "requires_response": False,
            "importance": 1,
            "suggested_followup_at": None,
            "memory_worthy": False,
            "memory_items": [],
            "message_summary": message_text[:240],
        }
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You classify incoming Telegram messages for a personal assistant. "
                            "Return only JSON. Be conservative about reminders: "
                            "requires_response is true only when the sender is clearly asking "
                            "a question, requesting an action/decision, making an invitation that "
                            "needs an answer, or expecting acknowledgement for coordination. "
                            "Set requires_response=false for FYI updates, thanks, reactions, "
                            "conversation closers, bot/service notices, or messages already "
                            "answered by the prior conversation. Do not copy full conversations. "
                            "Summaries must be brief. Memory items must be stable facts or explicit "
                            "commitments/preferences, never gossip or private raw message text. "
                            "suggested_followup_at must be ISO-8601 UTC or null; set it only when "
                            "the message names a concrete reply deadline."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Now UTC: {datetime.now(timezone.utc).isoformat()}\n"
                            f"Chat type: {chat_type}\n"
                            f"Sender: {sender_name}\n"
                            f"Prior summary, if any: {conversation_summary or 'none'}\n\n"
                            f"Incoming message:\n{message_text[:1500]}\n\n"
                            "JSON schema: {"
                            '"requires_response": boolean, '
                            '"importance": integer 1-5, '
                            '"suggested_followup_at": string|null, '
                            '"memory_worthy": boolean, '
                            '"memory_items": [string], '
                            '"message_summary": string'
                            "}"
                        ),
                    },
                ],
                temperature=0,
                max_tokens=350,
                extra_body={"response_format": {"type": "json_object"}},
            )
            raw = response.choices[0].message.content or "{}"
            data = json.loads(_clean_json(raw))
            data["classification_available"] = True
            data["requires_response"] = bool(
                data.get("requires_response", fallback["requires_response"])
            )
            data["importance"] = max(1, min(5, int(data.get("importance", 3) or 3)))
            data["memory_worthy"] = bool(data.get("memory_worthy", False))
            data["memory_items"] = [
                str(item).strip()[:300]
                for item in (data.get("memory_items") or [])
                if str(item).strip()
            ][:5]
            data["message_summary"] = str(
                data.get("message_summary") or fallback["message_summary"]
            )[:500]
            data["suggested_followup_at"] = self._parse_deadline(
                data.get("suggested_followup_at")
            )
            return data
        except Exception as exc:
            logger.warning("Userbot thread classifier failed: {}", exc)
            return fallback

    async def create_or_update_incoming(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        chat_id: int,
        chat_type: str,
        sender_tg_id: int,
        sender_name: str,
        message_id: int,
        message_text: str,
        suggested_replies: list[str],
        classification: dict[str, Any] | None = None,
    ) -> Any:
        cls = self._thread_model()
        classification = classification or await self.classify_message(
            message_text=message_text,
            sender_name=sender_name,
            chat_type=chat_type,
        )
        now = datetime.now(timezone.utc)
        deadline = self._parse_deadline(classification.get("suggested_followup_at"))
        requires_response = bool(classification.get("requires_response", True))

        result = await session.execute(
            select(cls)
            .where(
                cls.user_id == user_id,
                cls.chat_id == chat_id,
                cls.status.in_(OPEN_STATUSES),
            )
            .order_by(cls.last_incoming_at.desc())
            .limit(1)
        )
        thread = result.scalar_one_or_none()
        if not thread:
            thread = cls(
                user_id=user_id,
                chat_id=chat_id,
                chat_type=chat_type,
                sender_tg_id=sender_tg_id,
                sender_name=sender_name,
            )

        thread.message_id = message_id
        # Do not persist raw userbot message text; keep only summary/facts.
        thread.message_text = None
        thread.message_summary = (
            classification.get("message_summary") or message_text[:240]
        )
        thread.suggested_replies_json = (suggested_replies or [])[:3]
        thread.status = "open" if requires_response else "closed"
        thread.importance = int(classification.get("importance", 3) or 3)
        thread.requires_response = requires_response
        thread.memory_worthy = bool(classification.get("memory_worthy", False))
        thread.memory_items_json = classification.get("memory_items") or []
        thread.response_deadline_at = deadline if requires_response else None
        thread.last_incoming_at = now
        if hasattr(thread, "updated_at"):
            thread.updated_at = now

        session.add(thread)
        await session.flush()
        await self.ingest_memory_if_needed(session, thread)
        return thread

    async def attach_notification(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        thread_id: int | None,
        notification_chat_id: int | None,
        notification_message_id: int | None,
        pending_key: str | None = None,
    ) -> bool:
        if not thread_id or not notification_chat_id or not notification_message_id:
            return False
        cls = self._thread_model()
        thread = await session.get(cls, thread_id)
        if not thread or thread.user_id != user_id:
            return False
        if thread.status not in OPEN_STATUSES:
            return False
        now = datetime.now(timezone.utc)
        thread.notification_chat_id = notification_chat_id
        thread.notification_message_id = notification_message_id
        thread.notification_sent_at = now
        thread.pending_key = pending_key
        if hasattr(thread, "updated_at"):
            thread.updated_at = now
        session.add(thread)
        return True

    async def clear_notifications_for_read(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        chat_id: int,
        max_read_message_id: int,
    ) -> list[dict[str, Any]]:
        cls = self._thread_model()
        result = await session.execute(
            select(cls)
            .where(
                cls.user_id == user_id,
                cls.chat_id == chat_id,
                cls.status.in_(OPEN_STATUSES),
                cls.message_id.is_not(None),
                cls.message_id <= max_read_message_id,
                or_(
                    cls.notification_message_id.is_not(None),
                    cls.pending_key.is_not(None),
                ),
            )
            .order_by(cls.last_incoming_at.desc())
        )
        targets = []
        now = datetime.now(timezone.utc)
        for thread in result.scalars().all():
            targets.append(_notification_cleanup_target(thread))
            _clear_notification_fields(thread)
            if hasattr(thread, "updated_at"):
                thread.updated_at = now
            session.add(thread)
        return targets

    async def mark_replied_by_outgoing(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        chat_id: int,
        message_id: int | None = None,
        chat_type: str | None = None,
        reply_to_message_id: int | None = None,
    ) -> dict[str, Any] | None:
        cls = self._thread_model()
        filters = [
            cls.user_id == user_id,
            cls.chat_id == chat_id,
            cls.status.in_(OPEN_STATUSES),
        ]
        if reply_to_message_id:
            filters.append(cls.message_id == reply_to_message_id)
        elif message_id:
            filters.append(or_(cls.message_id.is_(None), cls.message_id <= message_id))
        if chat_type:
            filters.append(cls.chat_type == chat_type)

        result = await session.execute(
            select(cls).where(*filters).order_by(cls.last_incoming_at.desc()).limit(1)
        )
        thread = result.scalar_one_or_none()
        if not thread:
            return None
        cleanup_target = _notification_cleanup_target(thread)
        now = datetime.now(timezone.utc)
        thread.status = "replied"
        thread.last_outgoing_at = now
        thread.response_deadline_at = None
        _clear_notification_fields(thread)
        if hasattr(thread, "updated_at"):
            thread.updated_at = now
        session.add(thread)
        return cleanup_target

    async def mark_replied(
        self, session: AsyncSession, *, user_id: int, thread_id: int | None
    ) -> bool:
        if not thread_id:
            return False
        cls = self._thread_model()
        thread = await session.get(cls, thread_id)
        if not thread or thread.user_id != user_id:
            return False
        now = datetime.now(timezone.utc)
        thread.status = "replied"
        thread.last_outgoing_at = now
        thread.response_deadline_at = None
        _clear_notification_fields(thread)
        if hasattr(thread, "updated_at"):
            thread.updated_at = now
        session.add(thread)
        return True

    async def ingest_memory_if_needed(self, session: AsyncSession, thread: Any) -> bool:
        if not getattr(thread, "memory_worthy", False):
            return False
        user_settings = await self._get_user_settings(session, thread.user_id)
        if user_settings and not getattr(
            user_settings, "enable_userbot_memory_ingest", True
        ):
            return False
        memory_items = _as_list(getattr(thread, "memory_items_json", None))
        summary = getattr(thread, "message_summary", "") or ""
        if not summary and not memory_items:
            return False
        safe_text = (
            "Userbot message summary for memory extraction only.\n"
            f"Sender: {getattr(thread, 'sender_name', 'unknown')}\n"
            f"Chat type: {getattr(thread, 'chat_type', 'unknown')}\n"
            f"Summary: {summary[:500]}\n"
            f"Conservative facts: {'; '.join(memory_items)[:1000]}"
        )
        try:
            from .extractor_service import ExtractorService

            return await ExtractorService().find_write_important_info(
                user_id=thread.user_id,
                session=session,
                text=safe_text,
            )
        except Exception as exc:
            logger.debug(
                "Userbot memory ingest skipped for thread {}: {}",
                getattr(thread, "id", None),
                exc,
            )
            return False

    async def _get_user_settings(
        self, session: AsyncSession, user_id: int
    ) -> UserSettings | None:
        result = await session.execute(
            select(UserSettings).where(UserSettings.user_id == user_id)
        )
        return result.scalar_one_or_none()

    def _parse_deadline(self, raw: Any) -> datetime | None:
        """Parse an explicit deadline; returns None when absent or invalid."""
        if isinstance(raw, datetime):
            return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
        if isinstance(raw, str) and raw.strip():
            try:
                value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        return None


def _clean_json(raw: str) -> str:
    return re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item) for item in parsed if str(item).strip()]
        except json.JSONDecodeError:
            return [value]
    return []


def _notification_cleanup_target(thread: Any) -> dict[str, Any]:
    return {
        "thread_id": getattr(thread, "id", None),
        "notification_chat_id": getattr(thread, "notification_chat_id", None),
        "notification_message_id": getattr(thread, "notification_message_id", None),
        "pending_key": getattr(thread, "pending_key", None),
    }


def _clear_notification_fields(thread: Any) -> None:
    thread.notification_chat_id = None
    thread.notification_message_id = None
    thread.notification_sent_at = None
    thread.pending_key = None
