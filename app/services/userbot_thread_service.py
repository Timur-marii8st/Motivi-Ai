from __future__ import annotations

import html
import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

from aiogram import Bot
from loguru import logger
from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ..config import settings as app_settings
from ..llm.client import async_client
from ..models.settings import UserSettings
from ..models.users import User
from ..utils.telegram_topics import topic_kwargs_for_user


OPEN_STATUSES = ("open", "reminded")
CLOSED_STATUSES = ("replied", "dismissed", "closed")


class UserBotThreadService:
    """Persistent follow-up state for userbot DM/group suggestions."""

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
            "requires_response": True,
            "importance": 3,
            "suggested_followup_at": self._default_deadline().isoformat(),
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
                            "Return only JSON. Be conservative. Do not copy full conversations. "
                            "Summaries must be brief. Memory items must be stable facts or explicit "
                            "commitments/preferences, never gossip or private raw message text. "
                            "suggested_followup_at must be ISO-8601 UTC or null."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Now UTC: {datetime.now(timezone.utc).isoformat()}\n"
                            f"Default follow-up delay minutes: {app_settings.USERBOT_DEFAULT_FOLLOWUP_MINUTES}\n"
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
        thread.suggested_replies_json = suggested_replies[:3]
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

    async def mark_replied_by_outgoing(
        self, session: AsyncSession, *, user_id: int, chat_id: int
    ) -> bool:
        cls = self._thread_model()
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
            return False
        now = datetime.now(timezone.utc)
        thread.status = "replied"
        thread.last_outgoing_at = now
        if hasattr(thread, "updated_at"):
            thread.updated_at = now
        session.add(thread)
        return True

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
        if hasattr(thread, "updated_at"):
            thread.updated_at = now
        session.add(thread)
        return True

    async def mark_dismissed(
        self,
        session: AsyncSession,
        *,
        thread_id: int | None = None,
        pending_key: str | None = None,
        pending_metadata: dict[str, Any] | None = None,
    ) -> bool:
        cls = self._thread_model()
        pending = pending_metadata
        if not pending and pending_key:
            try:
                from .userbot_monitor import get_pending_reply

                pending = await get_pending_reply(pending_key)
            except Exception as exc:
                logger.debug("Could not resolve pending reply {}: {}", pending_key, exc)

        thread = await session.get(cls, thread_id) if thread_id else None
        if not thread and pending:
            result = await session.execute(
                select(cls)
                .where(
                    cls.user_id == pending.get("user_id"),
                    cls.chat_id == pending.get("chat_id"),
                    cls.message_id == pending.get("message_id"),
                    cls.status.in_(OPEN_STATUSES),
                )
                .order_by(cls.last_incoming_at.desc())
                .limit(1)
            )
            thread = result.scalar_one_or_none()
        if not thread:
            return False
        now = datetime.now(timezone.utc)
        thread.status = "dismissed"
        if hasattr(thread, "updated_at"):
            thread.updated_at = now
        session.add(thread)
        return True

    async def due_followups(
        self,
        session: AsyncSession,
        *,
        user_id: int | None = None,
        limit: int = 100,
    ) -> list[Any]:
        cls = self._thread_model()
        now = datetime.now(timezone.utc)
        cooldown_cutoff = now - timedelta(
            hours=app_settings.USERBOT_FOLLOWUP_REMINDER_COOLDOWN_HOURS
        )
        filters = [
            cls.requires_response == True,  # noqa: E712
            cls.status.notin_(CLOSED_STATUSES),
            cls.response_deadline_at.is_not(None),
            cls.response_deadline_at <= now,
            or_(cls.reminded_at.is_(None), cls.reminded_at <= cooldown_cutoff),
        ]
        if user_id is not None:
            filters.append(cls.user_id == user_id)
        result = await session.execute(
            select(cls)
            .where(*filters)
            .order_by(cls.importance.desc(), cls.response_deadline_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def send_due_followups(
        self,
        session: AsyncSession,
        bot: Bot,
        *,
        user_id: int | None = None,
    ) -> int:
        sent = 0
        for thread in await self.due_followups(session, user_id=user_id):
            if not await self._can_send_followup(session, thread.user_id):
                continue
            user = await session.get(User, thread.user_id)
            if not user:
                continue
            user_settings = await self._get_user_settings(session, thread.user_id)
            if user_settings and self._is_break_mode_active(user_settings):
                continue
            if user_settings and not getattr(
                user_settings, "enable_userbot_followups", True
            ):
                continue

            suggestions = _as_list(thread.suggested_replies_json)[:3]
            text = self._format_followup(thread, suggestions)
            keyboard = None
            if suggestions and (
                not user_settings
                or getattr(user_settings, "enable_reply_approval", True)
            ):
                try:
                    from .userbot_monitor import (
                        _build_approval_keyboard,
                        _store_pending_reply,
                    )

                    pending_key = await _store_pending_reply(
                        user_id=thread.user_id,
                        chat_id=thread.chat_id,
                        message_id=thread.message_id,
                        sender_name=thread.sender_name,
                        sender_tg_id=thread.sender_tg_id,
                        chat_type=thread.chat_type,
                        suggestions=suggestions,
                        thread_id=getattr(thread, "id", None),
                    )
                    keyboard = _build_approval_keyboard(pending_key, len(suggestions))
                except Exception as exc:
                    logger.debug("Could not attach userbot approval keyboard: {}", exc)

            await bot.send_message(
                user.tg_chat_id,
                text,
                parse_mode="HTML",
                reply_markup=keyboard,
                **topic_kwargs_for_user(user),
            )
            thread.reminded_at = datetime.now(timezone.utc)
            thread.status = "reminded"
            if hasattr(thread, "updated_at"):
                thread.updated_at = thread.reminded_at
            session.add(thread)
            await self._increment_followup_counter(thread.user_id)
            sent += 1
        return sent

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

    async def _can_send_followup(self, session: AsyncSession, user_id: int) -> bool:
        user_settings = await self._get_user_settings(session, user_id)
        if user_settings and not getattr(
            user_settings, "enable_userbot_followups", True
        ):
            return False
        current = await self._get_followup_counter(user_id)
        max_per_day = getattr(user_settings, "userbot_followup_max_per_day", None)
        if max_per_day is None:
            max_per_day = app_settings.USERBOT_MAX_FOLLOWUPS_PER_DAY
        return current < max_per_day

    @staticmethod
    def _is_break_mode_active(user_settings: UserSettings) -> bool:
        if not getattr(user_settings, "break_mode_active", False):
            return False
        until = getattr(user_settings, "break_mode_until", None)
        if until and until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        return not until or until > datetime.now(timezone.utc)

    async def _get_followup_counter(self, user_id: int) -> int:
        from redis.asyncio import Redis

        redis = Redis.from_url(app_settings.REDIS_URL)
        try:
            raw = await redis.get(_rate_key(user_id))
            return int(raw) if raw else 0
        finally:
            await redis.aclose()

    async def _increment_followup_counter(self, user_id: int) -> None:
        from redis.asyncio import Redis

        redis = Redis.from_url(app_settings.REDIS_URL)
        try:
            async with redis.pipeline(transaction=True) as pipe:
                pipe.incr(_rate_key(user_id))
                pipe.execute_command("EXPIRE", _rate_key(user_id), 90_000, "NX")
                await pipe.execute()
        finally:
            await redis.aclose()

    def _format_followup(self, thread: Any, suggestions: list[str]) -> str:
        sender = html.escape(getattr(thread, "sender_name", None) or "Someone")
        summary = html.escape(
            getattr(thread, "message_summary", None)
            or "They may be waiting for your reply."
        )
        lines = [f"<b>Follow-up reminder: {sender}</b>", summary]
        if suggestions:
            lines.append("")
            lines.append("<b>Suggested replies:</b>")
            lines.extend(
                f"{idx}. {html.escape(text)}" for idx, text in enumerate(suggestions, 1)
            )
        return "\n".join(lines)

    def _parse_deadline(self, raw: Any) -> datetime:
        if isinstance(raw, datetime):
            return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
        if isinstance(raw, str) and raw.strip():
            try:
                value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        return self._default_deadline()

    @staticmethod
    def _default_deadline() -> datetime:
        return datetime.now(timezone.utc) + timedelta(
            minutes=app_settings.USERBOT_DEFAULT_FOLLOWUP_MINUTES
        )


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


def _rate_key(user_id: int) -> str:
    return f"ub_followups:{user_id}:{date.today().isoformat()}"
