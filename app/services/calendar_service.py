from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ..config import settings as app_settings
from ..llm.client import async_client
from ..models.calendar_event import CalendarEvent
from ..models.users import User

MAX_EVENTS_PER_MESSAGE = 3
MAX_TITLE_LENGTH = 120


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso_to_utc(iso_str: str, tzname: str) -> datetime | None:
    """Parse an ISO datetime; naive values are treated as *tzname* local time."""
    raw = (iso_str or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        try:
            parsed = parsed.replace(tzinfo=ZoneInfo(tzname))
        except Exception:
            parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_local(dt: datetime, tzname: str, with_date: bool = True) -> str:
    try:
        local = dt.astimezone(ZoneInfo(tzname))
    except Exception:
        local = dt.astimezone(timezone.utc)
    if with_date:
        return local.strftime("%d.%m %H:%M")
    return local.strftime("%H:%M")


class CalendarService:
    """CRUD + reminder scheduling for Motivi's internal calendar."""

    @staticmethod
    async def create_event(
        session: AsyncSession,
        *,
        user_id: int,
        title: str,
        starts_at: datetime,
        ends_at: datetime | None = None,
        description: str | None = None,
        all_day: bool = False,
        source_type: str = "manual",
        source_name: str | None = None,
        source_chat_id: int | None = None,
        source_message_id: int | None = None,
        remind_before_minutes: int | None = None,
        bot=None,
        notify_chat_id: int | None = None,
    ) -> CalendarEvent | None:
        """Create an event and schedule its reminder. Returns None for duplicates/past events."""
        title = " ".join((title or "").split())[:MAX_TITLE_LENGTH]
        if not title:
            return None

        if starts_at.tzinfo is None:
            starts_at = starts_at.replace(tzinfo=timezone.utc)
        starts_at = starts_at.astimezone(timezone.utc)
        if starts_at <= utc_now():
            logger.debug(
                "Calendar: skipping past event for user {} ({})", user_id, title
            )
            return None

        if ends_at is not None:
            if ends_at.tzinfo is None:
                ends_at = ends_at.replace(tzinfo=timezone.utc)
            ends_at = ends_at.astimezone(timezone.utc)
            if ends_at <= starts_at:
                ends_at = None

        # Deduplicate events extracted from the same source message.
        if source_chat_id is not None and source_message_id is not None:
            result = await session.execute(
                select(CalendarEvent).where(
                    CalendarEvent.user_id == user_id,
                    CalendarEvent.source_chat_id == source_chat_id,
                    CalendarEvent.source_message_id == source_message_id,
                    CalendarEvent.status == "active",
                )
            )
            for existing in result.scalars().all():
                if (existing.title or "").strip().lower() == title.strip().lower():
                    logger.debug(
                        "Calendar: duplicate event skipped for user {} ({})",
                        user_id,
                        title,
                    )
                    return None

        event = CalendarEvent(
            user_id=user_id,
            title=title,
            description=(description or None),
            starts_at=starts_at,
            ends_at=ends_at,
            all_day=all_day,
            source_type=source_type,
            source_name=source_name,
            source_chat_id=source_chat_id,
            source_message_id=source_message_id,
            remind_before_minutes=(
                remind_before_minutes if remind_before_minutes is not None else 15
            ),
        )
        session.add(event)
        await session.flush()

        event.reminder_job_id = CalendarService.schedule_reminder(event)
        session.add(event)

        if bot is not None and notify_chat_id:
            try:
                user = await session.get(User, user_id)
                tzname = (user.user_timezone if user else None) or "UTC"
                from ..utils.telegram_topics import topic_kwargs_for_user

                await bot.send_message(
                    notify_chat_id,
                    (
                        f"📅 <b>Added to calendar:</b> {_esc(title)}\n"
                        f"🕒 {format_local(starts_at, tzname)}"
                    ),
                    parse_mode="HTML",
                    **topic_kwargs_for_user(user),
                )
            except Exception as exc:
                logger.debug("Calendar: creation notification failed: {}", exc)

        logger.info(
            "Calendar: created event {} for user {} at {} ({})",
            event.id,
            user_id,
            starts_at,
            title,
        )
        return event

    @staticmethod
    def schedule_reminder(event: CalendarEvent) -> str | None:
        """Schedule the one-off reminder job for an active future event."""
        from ..scheduler.scheduler_instance import scheduler

        if event.id is None or event.status != "active":
            return None
        now = utc_now()
        if event.starts_at <= now:
            return None

        remind_at = event.starts_at - timedelta(
            minutes=max(0, int(event.remind_before_minutes or 0))
        )
        run_date = max(remind_at, now + timedelta(seconds=30))

        job_id = f"calendar_reminder_{event.id}"
        try:
            from apscheduler.triggers.date import DateTrigger

            scheduler.add_job(
                func="app.scheduler.jobs:calendar_reminder_job",
                trigger=DateTrigger(run_date=run_date, timezone=timezone.utc),
                id=job_id,
                args=[event.id],
                replace_existing=True,
            )
        except Exception as exc:
            logger.warning(
                "Calendar: failed to schedule reminder for event {}: {}",
                event.id,
                exc,
            )
            return None
        return job_id

    @staticmethod
    def remove_reminder(event: CalendarEvent) -> None:
        from ..scheduler.scheduler_instance import scheduler

        job_id = event.reminder_job_id or (
            f"calendar_reminder_{event.id}" if event.id is not None else None
        )
        if not job_id:
            return
        try:
            if scheduler.get_job(job_id):
                scheduler.remove_job(job_id)
        except Exception as exc:
            logger.debug("Calendar: failed to remove job {}: {}", job_id, exc)
        event.reminder_job_id = None

    @staticmethod
    async def list_upcoming(
        session: AsyncSession,
        user_id: int,
        *,
        days: int = 7,
    ) -> list[CalendarEvent]:
        now = utc_now()
        horizon = now + timedelta(days=days)
        result = await session.execute(
            select(CalendarEvent)
            .where(
                CalendarEvent.user_id == user_id,
                CalendarEvent.status == "active",
                CalendarEvent.starts_at >= now - timedelta(hours=12),
                CalendarEvent.starts_at <= horizon,
            )
            .order_by(CalendarEvent.starts_at.asc())
            .limit(30)
        )
        return list(result.scalars().all())

    @staticmethod
    async def events_for_date(
        session: AsyncSession,
        user_id: int,
        day: datetime,
        tzname: str,
    ) -> list[CalendarEvent]:
        """Active events starting on the given user-local day."""
        tz: timezone | ZoneInfo
        try:
            tz = ZoneInfo(tzname)
        except Exception:
            tz = timezone.utc
        local_day = day.astimezone(tz).date()
        day_start = datetime.combine(local_day, datetime.min.time(), tzinfo=tz)
        day_end = day_start + timedelta(days=1)
        result = await session.execute(
            select(CalendarEvent)
            .where(
                CalendarEvent.user_id == user_id,
                CalendarEvent.status == "active",
                CalendarEvent.starts_at >= day_start.astimezone(timezone.utc),
                CalendarEvent.starts_at < day_end.astimezone(timezone.utc),
            )
            .order_by(CalendarEvent.starts_at.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_for_user(
        session: AsyncSession, event_id: int, user_id: int
    ) -> CalendarEvent | None:
        event = await session.get(CalendarEvent, event_id)
        if not event or event.user_id != user_id:
            return None
        return event

    @staticmethod
    async def set_status(
        session: AsyncSession, event_id: int, user_id: int, status: str
    ) -> CalendarEvent | None:
        event = await CalendarService.get_for_user(session, event_id, user_id)
        if not event:
            return None
        CalendarService.remove_reminder(event)
        event.status = status
        event.touch()
        session.add(event)
        return event

    @staticmethod
    async def postpone(
        session: AsyncSession, event_id: int, user_id: int, minutes: int
    ) -> CalendarEvent | None:
        event = await CalendarService.get_for_user(session, event_id, user_id)
        if not event or event.status != "active":
            return None
        delta = timedelta(minutes=minutes)
        CalendarService.remove_reminder(event)
        event.starts_at = event.starts_at + delta
        if event.ends_at is not None:
            event.ends_at = event.ends_at + delta
        event.reminded_at = None
        event.reminder_job_id = CalendarService.schedule_reminder(event)
        event.touch()
        session.add(event)
        return event


class CalendarExtractionService:
    """LLM extraction of calendar-worthy events from messages and posts."""

    def __init__(self) -> None:
        self.client = async_client
        self.model = app_settings.EXTRACTOR_MODEL_ID

    async def extract_events(
        self,
        *,
        text: str,
        tzname: str,
        source_type: str,
        source_name: str | None,
    ) -> list[dict[str, Any]]:
        """Return up to MAX_EVENTS_PER_MESSAGE candidate events (UTC datetimes)."""
        fallback: list[dict[str, Any]] = []
        clean_text = (text or "").strip()
        if not clean_text:
            return fallback
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You extract calendar events from Telegram messages for a "
                            "personal assistant. Return ONLY JSON of the form "
                            '{"events": [...]}. An event qualifies only when it has a '
                            "concrete date/time: meetings, calls, appointments, deadlines "
                            "('send X by Friday'), dated events (webinars, releases, exams, "
                            "flights, parties). Do NOT create events for vague intentions, "
                            "questions without dates, or simple reply obligations. "
                            "Deadlines without an exact time use 23:59. Date-only events "
                            "use 09:00 and set all_day=true. Titles are short (max 60 "
                            f"chars), in the language of the text. Max {MAX_EVENTS_PER_MESSAGE} events. "
                            "All datetimes are LOCAL user time, format YYYY-MM-DDTHH:MM:SS "
                            "without timezone suffix."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Now UTC: {utc_now().isoformat()}\n"
                            f"User timezone: {tzname}\n"
                            f"Source: {source_type}"
                            + (f' "{source_name}"' if source_name else "")
                            + "\n\nText:\n"
                            f"{clean_text[:2000]}\n\n"
                            'JSON schema: {"events": [{"title": string, '
                            '"starts_at_iso": string, "ends_at_iso": string|null, '
                            '"all_day": boolean, "remind_before_minutes": integer|null}]}'
                        ),
                    },
                ],
                temperature=0,
                max_tokens=500,
                extra_body={"response_format": {"type": "json_object"}},
            )
            raw = response.choices[0].message.content or "{}"
            data = json.loads(_clean_json(raw))
            return self._sanitize_events(data, tzname)
        except Exception as exc:
            logger.debug("Calendar extraction failed: {}", exc)
            return fallback

    def _sanitize_events(
        self, data: dict[str, Any], tzname: str
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        raw_events = data.get("events")
        if not isinstance(raw_events, list):
            return events

        now = utc_now()
        for raw in raw_events[:MAX_EVENTS_PER_MESSAGE]:
            if not isinstance(raw, dict):
                continue
            title = " ".join(str(raw.get("title") or "").split())[:MAX_TITLE_LENGTH]
            starts_at = parse_iso_to_utc(str(raw.get("starts_at_iso") or ""), tzname)
            if not title or starts_at is None or starts_at <= now:
                continue
            ends_at = parse_iso_to_utc(str(raw.get("ends_at_iso") or ""), tzname)
            if ends_at is not None and ends_at <= starts_at:
                ends_at = None
            remind_before = raw.get("remind_before_minutes")
            try:
                remind_before = (
                    int(remind_before) if remind_before is not None else None
                )
            except (TypeError, ValueError):
                remind_before = None
            if remind_before is not None:
                remind_before = max(0, min(remind_before, 7 * 24 * 60))
            events.append(
                {
                    "title": title,
                    "starts_at": starts_at,
                    "ends_at": ends_at,
                    "all_day": bool(raw.get("all_day", False)),
                    "remind_before_minutes": remind_before,
                }
            )
        return events


def _clean_json(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        json.loads(text)
        return text
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match:
            return match.group(0)
        return "{}"


def _esc(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
