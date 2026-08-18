"""
UserBotMonitor — Telethon event handlers and LLM-powered notification logic.

Four types of events are handled:
  1. New posts in channels the user is subscribed to.
     → An LLM classifies whether the post is relevant to the user's interests.
       If yes, a formatted notification is sent via the bot. High-priority
       posts are additionally scanned for calendar-worthy items.
  2. Incoming private messages (DMs) to the user's personal account.
     → The message is classified; important messages produce a notification
       and any concrete dates/deadlines are added to Motivi's calendar.
  3. Incoming group/supergroup messages mentioning the user or replying to them.
     → Same as DMs.
  4. Outgoing messages from the user (DMs and groups).
     → Used to detect that the user already answered, so notifications for
       handled conversations are cleaned up.

Motivi never sends messages on behalf of the user: the account is monitored
read-only. Calendar events extracted from messages get automatic reminders.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING

from loguru import logger
from telethon import TelegramClient, events

from ..config import settings as app_settings
from ..llm.client import async_client
from ..utils.telegram_topics import topic_kwargs_for_user
from .userbot_state_probe import (
    cache_read_marker,
    get_cached_read_marker,
    get_read_inbox_max_id,
    has_cached_manual_outgoing_after,
)

if TYPE_CHECKING:
    from aiogram import Bot


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------


def setup_handlers(client: TelegramClient, user_id: int, bot: "Bot") -> None:
    """Register all Telethon event handlers for *one* user's client."""
    assistant_bot_id: int | None = None

    async def resolve_assistant_bot_id() -> int | None:
        nonlocal assistant_bot_id
        if assistant_bot_id is not None:
            return assistant_bot_id
        try:
            assistant_bot_id = int((await bot.get_me()).id)
        except Exception as exc:
            logger.debug(
                "Could not resolve aiogram bot id for userbot filters: {}", exc
            )
        return assistant_bot_id

    @client.on(
        events.NewMessage(incoming=True, func=lambda e: e.is_channel and not e.is_group)
    )
    async def on_channel_post(event):
        await _handle_channel_post(event, user_id, bot)

    @client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
    async def on_dm(event):
        await _handle_dm(
            event,
            user_id,
            bot,
            client,
            assistant_bot_id=await resolve_assistant_bot_id(),
        )

    @client.on(events.NewMessage(incoming=True, func=lambda e: e.is_group))
    async def on_group(event):
        await _handle_group_message(
            event,
            user_id,
            bot,
            client,
            assistant_bot_id=await resolve_assistant_bot_id(),
        )

    # Track the user's own outgoing messages to detect manual replies
    @client.on(
        events.NewMessage(outgoing=True, func=lambda e: e.is_private or e.is_group)
    )
    async def on_outgoing(event):
        await _handle_outgoing_message(
            event,
            user_id,
            bot=bot,
            assistant_bot_id=await resolve_assistant_bot_id(),
        )

    @client.on(events.MessageRead(inbox=True))
    async def on_message_read(event):
        await _handle_message_read(event, user_id, bot)


# ---------------------------------------------------------------------------
# Channel post handler
# ---------------------------------------------------------------------------


def _is_break_mode_active(user_settings) -> bool:
    if not getattr(user_settings, "break_mode_active", False):
        return False
    until = getattr(user_settings, "break_mode_until", None)
    if until and until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    return not until or until > datetime.now(timezone.utc)


async def _handle_message_read(event, user_id: int, bot: Bot | None = None) -> None:
    """Track inbox read events so we can skip already-read messages."""
    try:
        chat_id = getattr(event, "chat_id", None)
        max_read = getattr(event, "max_id", None) or getattr(event, "max_read", None)
        if not chat_id or not max_read:
            return
        max_read_id = int(max_read)
        await cache_read_marker(user_id, chat_id, max_read_id)
        if bot:
            await _clear_read_thread_notifications(
                user_id=user_id,
                chat_id=chat_id,
                max_read_message_id=max_read_id,
                bot=bot,
            )
    except Exception as exc:
        logger.debug("MessageRead handler error (user {}): {}", user_id, exc)


async def _check_if_message_read(
    client: TelegramClient,
    user_id: int,
    chat_id: int,
    message_id: int,
) -> bool:
    """Return True if the message has already been read by the user."""
    # 1. Fast path: Redis cache from live MessageRead events
    cached_max = await get_cached_read_marker(user_id, chat_id)
    if cached_max is not None and cached_max >= message_id:
        return True

    # 2. Fallback: ask Telethon for the current dialog read cursor
    read_max = await get_read_inbox_max_id(client, chat_id)
    if read_max is not None:
        await cache_read_marker(user_id, chat_id, read_max)
        return read_max >= message_id

    return False


async def _handle_channel_post(event, user_id: int, bot: "Bot") -> None:
    try:
        user_settings = await _get_user_settings(user_id)
        if user_settings and not user_settings.enable_channel_monitoring:
            return
        if user_settings and _is_break_mode_active(user_settings):
            return

        chat = await event.get_chat()
        if getattr(chat, "megagroup", False):
            return

        text: str = event.message.message or ""
        if len(text) < 30:
            return

        # Rate limit check BEFORE LLM call
        channel_id = event.chat_id
        today_str = date.today().isoformat()
        rate_key = f"userbot_notif:{user_id}:{channel_id}:{today_str}"

        redis = await _get_redis()
        try:
            async with redis.pipeline(transaction=True) as pipe:
                pipe.incr(rate_key)
                pipe.execute_command("EXPIRE", rate_key, 90_000, "NX")
                pipe_result = await pipe.execute()
            count = int(pipe_result[0])
            if count > app_settings.USERBOT_MAX_CHANNEL_NOTIFS_PER_DAY:
                return
        finally:
            await redis.aclose()

        # Classify with rich user context (core facts + interests + profile)
        interests = await _get_channel_interests(user_id)
        user_facts = await _get_user_core_facts(user_id)

        classification = await _classify_post_relevance(
            text=text,
            interests=interests,
            user_facts=user_facts,
        )

        score = classification["score"]
        summary = classification["summary"]

        # LOW relevance → skip
        if score < app_settings.USERBOT_CHANNEL_MEDIUM_THRESHOLD:
            return

        # Extract channel metadata
        channel_name = (
            getattr(chat, "title", None)
            or getattr(chat, "username", None)
            or f"channel {channel_id}"
        )
        channel_username = getattr(chat, "username", None)

        post_link = ""
        if channel_username and event.message.id:
            post_link = f"https://t.me/{channel_username}/{event.message.id}"

        tg_id, topic_kwargs = await _get_tg_delivery(user_id)
        if not tg_id:
            return

        # HIGH relevance → send immediately with detail + calendar extraction
        if score >= app_settings.USERBOT_CHANNEL_HIGH_THRESHOLD:
            calendar_events = await _extract_calendar_events(
                user_id=user_id,
                text=text,
                source_type="channel",
                source_name=channel_name,
                source_chat_id=channel_id,
                source_message_id=event.message.id,
            )

            reason = classification.get("reason", "")
            notification = _format_high_priority_notification(
                channel_name=channel_name,
                summary=summary,
                reason=reason,
                post_link=post_link,
            )
            calendar_lines = await _format_calendar_lines(user_id, calendar_events)
            if calendar_lines:
                notification += "\n" + calendar_lines
            await bot.send_message(
                tg_id,
                notification,
                parse_mode="HTML",
                disable_web_page_preview=True,
                **topic_kwargs,
            )
            # Save to conversation history so LLM knows what user was notified about
            await _save_notification_to_history(
                tg_chat_id=tg_id,
                text=f"[Channel notification from {channel_name}]: {summary}",
            )
            logger.info(
                "Userbot: sent HIGH-priority channel notification to user {} from {} (score={})",
                user_id,
                channel_name,
                score,
            )
        else:
            # MEDIUM relevance → accumulate in batch
            await _add_to_channel_batch(
                user_id=user_id,
                channel_name=channel_name,
                summary=summary,
                post_link=post_link,
                score=score,
            )
            # Auto-flush if batch is full
            batch_size = await _get_channel_batch_size(user_id)
            if batch_size >= app_settings.USERBOT_CHANNEL_BATCH_MAX:
                await flush_channel_batch(user_id, bot)

    except Exception as exc:
        logger.error("Userbot channel handler error (user {}): {}", user_id, exc)


# ---------------------------------------------------------------------------
# Outgoing message handler — manual reply detection and notification cleanup
# ---------------------------------------------------------------------------


async def _handle_outgoing_message(
    event,
    user_id: int,
    *,
    bot: Bot | None = None,
    assistant_bot_id: int | None = None,
) -> None:
    """Detect that the user answered manually and clean up open notifications."""
    try:
        if _is_private_chat_with_telegram_id(event, assistant_bot_id):
            return

        chat_id = _event_chat_id(event)
        if chat_id is None:
            return

        message_id = _coerce_int(getattr(event.message, "id", None))
        await _record_manual_outgoing(
            user_id=user_id,
            chat_id=chat_id,
            message_id=message_id,
        )

        cleanup_target = await _mark_latest_thread_replied(
            user_id=user_id,
            chat_id=chat_id,
            message_id=message_id,
            chat_type="group" if getattr(event, "is_group", False) else "dm",
            reply_to_message_id=_reply_to_message_id(event),
        )
        if cleanup_target:
            await _cleanup_thread_notification(
                bot=bot,
                cleanup_target=cleanup_target,
                reason="manual_reply",
            )

    except Exception as exc:
        logger.debug("Userbot outgoing handler error (user {}): {}", user_id, exc)


# ---------------------------------------------------------------------------
# DM handler
# ---------------------------------------------------------------------------


async def _handle_dm(
    event,
    user_id: int,
    bot: "Bot",
    client: TelegramClient,
    *,
    assistant_bot_id: int | None = None,
) -> None:
    """Fast path: enqueue delayed processing so we can skip already-read messages."""
    try:
        if _is_outgoing_event(event) or _should_ignore_assistant_bot_event(
            event, assistant_bot_id
        ):
            return

        text: str = event.message.message or ""
        if not text.strip():
            return

        sender = await event.get_sender()
        if _is_telegram_bot_sender(sender):
            return

        sender_tg_id = (
            _coerce_int(getattr(sender, "id", None))
            or _event_sender_id(event)
            or _event_chat_id(event)
            or 0
        )
        batch_key, batch_version = await _enqueue_reply_batch_message(
            user_id=user_id,
            chat_id=event.chat_id,
            sender_tg_id=sender_tg_id,
            chat_type="dm",
            message_id=event.message.id,
            text=text,
        )
        asyncio.create_task(
            _process_dm_debounced(
                event=event,
                user_id=user_id,
                bot=bot,
                client=client,
                sender=sender,
                sender_tg_id=sender_tg_id,
                batch_key=batch_key,
                expected_batch_version=batch_version,
            )
        )
    except Exception as exc:
        logger.error("Userbot DM handler error (user {}): {}", user_id, exc)


async def _process_dm_debounced(
    event,
    user_id: int,
    bot: "Bot",
    client: TelegramClient,
    *,
    sender=None,
    sender_tg_id: int = 0,
    batch_key: str,
    expected_batch_version: int,
) -> None:
    """Wait for a quiet window, then process the DM batch if it is still current."""
    try:
        await asyncio.sleep(_reply_batch_delay_seconds())

        batch_messages = await _drain_reply_batch_if_current(
            batch_key=batch_key,
            expected_version=expected_batch_version,
        )
        if batch_messages is None:
            return

        user_settings = await _get_user_settings(user_id)
        if user_settings and not user_settings.enable_dm_notifications:
            return
        if user_settings and _is_break_mode_active(user_settings):
            return

        latest_message_id = _latest_batch_message_id(batch_messages, event.message.id)
        if await _check_if_message_read(
            client, user_id, event.chat_id, latest_message_id
        ):
            logger.info(
                "Userbot: skipping DM for user {} - message {} already read",
                user_id,
                latest_message_id,
            )
            return
        latest_message_ts = _latest_batch_ts(batch_messages)
        if await _has_manual_outgoing_after(
            user_id=user_id,
            chat_id=event.chat_id,
            message_id=latest_message_id,
            message_ts=latest_message_ts,
        ):
            logger.info(
                "Userbot: skipping DM for user {} - message {} already answered manually",
                user_id,
                latest_message_id,
            )
            return

        text = _batch_message_text(batch_messages)
        if not text:
            text = event.message.message or ""
        if not text.strip():
            return

        if sender is None:
            sender = await event.get_sender()
        if _is_telegram_bot_sender(sender):
            return

        first = getattr(sender, "first_name", None) or ""
        last = getattr(sender, "last_name", None) or ""
        sender_name = (
            f"{first} {last}".strip() or getattr(sender, "username", None) or "Someone"
        )
        sender_tg_id = sender_tg_id or getattr(sender, "id", 0)

        # Gather conversation context for classification
        thread = await _fetch_conversation_thread(client, event.chat_id)

        classification = await _classify_incoming_message(
            user_id=user_id,
            text=text,
            sender_name=sender_name,
            chat_type="dm",
            conversation_thread=thread,
        )
        if not _classification_available(classification):
            logger.warning(
                "Userbot: skipping DM for user {} - classifier unavailable",
                user_id,
            )
            return
        summary = classification.get("summary") or _short_summary(text)

        thread_id = await _persist_incoming_thread(
            user_id=user_id,
            chat_id=event.chat_id,
            message_id=latest_message_id,
            sender_name=sender_name,
            sender_tg_id=sender_tg_id,
            chat_type="dm",
            message_text=text,
            summary=summary,
            classification=classification,
        )

        # Calendar: extract concrete events + create a follow-up event when
        # the message expects an answer by a specific time.
        calendar_events = await _extract_calendar_events(
            user_id=user_id,
            text=text,
            source_type="dm",
            source_name=sender_name,
            source_chat_id=event.chat_id,
            source_message_id=latest_message_id,
        )
        followup_event = await _create_followup_event(
            user_id=user_id,
            classification=classification,
            sender_name=sender_name,
            summary=summary,
            source_type="dm",
            source_chat_id=event.chat_id,
            source_message_id=latest_message_id,
        )
        if followup_event:
            calendar_events.append(followup_event)

        requires_response = _classification_requires_response(classification)
        importance = _classification_importance(classification)
        if not requires_response and importance < 4:
            logger.info(
                "Userbot: skipping DM notification for user {} - not important enough",
                user_id,
            )
            return

        if await _check_if_message_read(
            client, user_id, event.chat_id, latest_message_id
        ):
            logger.info(
                "Userbot: skipping DM notification for user {} - message {} was read during processing",
                user_id,
                latest_message_id,
            )
            return
        if await _has_manual_outgoing_after(
            user_id=user_id,
            chat_id=event.chat_id,
            message_id=latest_message_id,
            message_ts=latest_message_ts,
        ):
            logger.info(
                "Userbot: skipping DM notification for user {} - message {} was answered during processing",
                user_id,
                latest_message_id,
            )
            return

        tg_id, topic_kwargs = await _get_tg_delivery(user_id)
        if not tg_id:
            return

        preview = _batch_preview(batch_messages, fallback=text)

        notification = (
            f"💬 <b>New message from {_esc(sender_name)}:</b>\n"
            f"━━━━━━━━━━━━\n"
            f"<i>{_esc(preview)}</i>\n"
            f"━━━━━━━━━━━━\n"
        )
        calendar_lines = await _format_calendar_lines(user_id, calendar_events)
        if calendar_lines:
            notification += calendar_lines + "\n"

        sent_message = await bot.send_message(
            tg_id,
            notification,
            parse_mode="HTML",
            **topic_kwargs,
        )

        await _attach_thread_notification(
            user_id=user_id,
            thread_id=thread_id,
            notification_chat_id=tg_id,
            notification_message_id=getattr(sent_message, "message_id", None),
        )

        logger.info(
            "Userbot: sent DM notification to user {} from {}", user_id, sender_name
        )
    except Exception as exc:
        logger.error("Userbot delayed DM handler error (user {}): {}", user_id, exc)


# ---------------------------------------------------------------------------
# Group message handler
# ---------------------------------------------------------------------------


async def _handle_group_message(
    event,
    user_id: int,
    bot: "Bot",
    client: TelegramClient,
    *,
    assistant_bot_id: int | None = None,
) -> None:
    """
    Fast path: filter then enqueue delayed processing so we can skip
    already-read messages.
    """
    try:
        if _is_outgoing_event(event) or _should_ignore_assistant_bot_event(
            event, assistant_bot_id
        ):
            return

        text: str = event.message.message or ""
        if not text.strip():
            return

        # Only process messages that are relevant to the user:
        # 1. Direct reply to user's message
        # 2. Message mentions the user
        me = await client.get_me()
        if _ids_equal(_event_sender_id(event), getattr(me, "id", None)):
            return

        sender = await event.get_sender()
        if _is_telegram_bot_sender(sender):
            return

        is_reply_to_me = False
        if event.message.reply_to:
            try:
                replied = await event.message.get_reply_message()
                if replied and replied.sender_id == me.id:
                    is_reply_to_me = True
            except Exception:
                pass

        is_mention = False
        if me.username and f"@{me.username}" in text:
            is_mention = True
        if hasattr(event.message, "entities") and event.message.entities:
            from telethon.tl.types import MessageEntityMentionName

            for ent in event.message.entities:
                if isinstance(ent, MessageEntityMentionName) and ent.user_id == me.id:
                    is_mention = True
                    break

        if not is_reply_to_me and not is_mention:
            return

        sender_tg_id = (
            _coerce_int(getattr(sender, "id", None)) or _event_sender_id(event) or 0
        )
        batch_key, batch_version = await _enqueue_reply_batch_message(
            user_id=user_id,
            chat_id=event.chat_id,
            sender_tg_id=sender_tg_id,
            chat_type="group",
            message_id=event.message.id,
            text=text,
        )
        asyncio.create_task(
            _process_group_debounced(
                event=event,
                user_id=user_id,
                bot=bot,
                client=client,
                is_reply_to_me=is_reply_to_me,
                sender=sender,
                sender_tg_id=sender_tg_id,
                batch_key=batch_key,
                expected_batch_version=batch_version,
            )
        )
    except Exception as exc:
        logger.error("Userbot group handler error (user {}): {}", user_id, exc)


async def _process_group_debounced(
    event,
    user_id: int,
    bot: "Bot",
    client: TelegramClient,
    *,
    is_reply_to_me: bool = False,
    sender=None,
    sender_tg_id: int = 0,
    batch_key: str,
    expected_batch_version: int,
) -> None:
    """Wait for a quiet window, then process the group message batch if current."""
    try:
        await asyncio.sleep(_reply_batch_delay_seconds())

        batch_messages = await _drain_reply_batch_if_current(
            batch_key=batch_key,
            expected_version=expected_batch_version,
        )
        if batch_messages is None:
            return

        user_settings = await _get_user_settings(user_id)
        if user_settings and not user_settings.enable_group_monitoring:
            return
        if user_settings and _is_break_mode_active(user_settings):
            return

        latest_message_id = _latest_batch_message_id(batch_messages, event.message.id)
        if await _check_if_message_read(
            client, user_id, event.chat_id, latest_message_id
        ):
            logger.info(
                "Userbot: skipping group msg for user {} - message {} already read",
                user_id,
                latest_message_id,
            )
            return
        latest_message_ts = _latest_batch_ts(batch_messages)
        if await _has_manual_outgoing_after(
            user_id=user_id,
            chat_id=event.chat_id,
            message_id=latest_message_id,
            message_ts=latest_message_ts,
        ):
            logger.info(
                "Userbot: skipping group msg for user {} - message {} already answered manually",
                user_id,
                latest_message_id,
            )
            return

        if not await _check_group_notification_rate_limit(user_id, event.chat_id):
            return

        text = _batch_message_text(batch_messages)
        if not text:
            text = event.message.message or ""
        if not text.strip():
            return

        if sender is None:
            sender = await event.get_sender()
        if _is_telegram_bot_sender(sender):
            return

        first = getattr(sender, "first_name", None) or ""
        last = getattr(sender, "last_name", None) or ""
        sender_name = (
            f"{first} {last}".strip() or getattr(sender, "username", None) or "Someone"
        )
        sender_tg_id = sender_tg_id or getattr(sender, "id", 0)

        chat = await event.get_chat()
        chat_title = getattr(chat, "title", None) or f"group {event.chat_id}"

        # Gather conversation context for classification
        thread = await _fetch_conversation_thread(client, event.chat_id)

        classification = await _classify_incoming_message(
            user_id=user_id,
            text=text,
            sender_name=sender_name,
            chat_type="group",
            conversation_thread=thread,
        )
        if not _classification_available(classification):
            logger.warning(
                "Userbot: skipping group notification for user {} - classifier unavailable",
                user_id,
            )
            return
        summary = classification.get("summary") or _short_summary(text)

        thread_id = await _persist_incoming_thread(
            user_id=user_id,
            chat_id=event.chat_id,
            message_id=latest_message_id,
            sender_name=sender_name,
            sender_tg_id=sender_tg_id,
            chat_type="group",
            message_text=text,
            summary=summary,
            classification=classification,
        )

        calendar_events = await _extract_calendar_events(
            user_id=user_id,
            text=text,
            source_type="group",
            source_name=sender_name,
            source_chat_id=event.chat_id,
            source_message_id=latest_message_id,
        )
        followup_event = await _create_followup_event(
            user_id=user_id,
            classification=classification,
            sender_name=sender_name,
            summary=summary,
            source_type="group",
            source_chat_id=event.chat_id,
            source_message_id=latest_message_id,
        )
        if followup_event:
            calendar_events.append(followup_event)

        requires_response = _classification_requires_response(classification)
        importance = _classification_importance(classification)
        if not requires_response and importance < 4:
            logger.info(
                "Userbot: skipping group notification for user {} - not important enough",
                user_id,
            )
            return

        if await _check_if_message_read(
            client, user_id, event.chat_id, latest_message_id
        ):
            logger.info(
                "Userbot: skipping group notification for user {} - message {} was read during processing",
                user_id,
                latest_message_id,
            )
            return
        if await _has_manual_outgoing_after(
            user_id=user_id,
            chat_id=event.chat_id,
            message_id=latest_message_id,
            message_ts=latest_message_ts,
        ):
            logger.info(
                "Userbot: skipping group notification for user {} - message {} was answered during processing",
                user_id,
                latest_message_id,
            )
            return

        tg_id, topic_kwargs = await _get_tg_delivery(user_id)
        if not tg_id:
            return

        preview = _batch_preview(batch_messages, fallback=text)

        trigger = "replied to you" if is_reply_to_me else "mentioned you"
        notification = (
            f"👥 <b>{_esc(sender_name)}</b> {trigger} in <b>{_esc(chat_title)}</b>:\n"
            f"━━━━━━━━━━━━\n"
            f"<i>{_esc(preview)}</i>\n"
            f"━━━━━━━━━━━━\n"
        )
        calendar_lines = await _format_calendar_lines(user_id, calendar_events)
        if calendar_lines:
            notification += calendar_lines + "\n"

        sent_message = await bot.send_message(
            tg_id,
            notification,
            parse_mode="HTML",
            **topic_kwargs,
        )

        await _attach_thread_notification(
            user_id=user_id,
            thread_id=thread_id,
            notification_chat_id=tg_id,
            notification_message_id=getattr(sent_message, "message_id", None),
        )

        logger.info(
            "Userbot: sent group notification to user {} from {} in {}",
            user_id,
            sender_name,
            chat_title,
        )
    except Exception as exc:
        logger.error("Userbot delayed group handler error (user {}): {}", user_id, exc)


# ---------------------------------------------------------------------------
# Calendar integration
# ---------------------------------------------------------------------------


async def _extract_calendar_events(
    *,
    user_id: int,
    text: str,
    source_type: str,
    source_name: str | None,
    source_chat_id: int | None,
    source_message_id: int | None,
) -> list:
    """Extract calendar-worthy items from message text and persist them."""
    try:
        user_settings = await _get_user_settings(user_id)
        if user_settings and not getattr(
            user_settings, "enable_calendar_extraction", True
        ):
            return []

        from ..db import get_session
        from .calendar_service import CalendarExtractionService, CalendarService

        tzname = await _get_user_timezone(user_id)
        candidates = await CalendarExtractionService().extract_events(
            text=text,
            tzname=tzname,
            source_type=source_type,
            source_name=source_name,
        )
        if not candidates:
            return []

        created = []
        async with get_session() as session:
            for candidate in candidates:
                event = await CalendarService.create_event(
                    session,
                    user_id=user_id,
                    title=candidate["title"],
                    starts_at=candidate["starts_at"],
                    ends_at=candidate.get("ends_at"),
                    all_day=bool(candidate.get("all_day", False)),
                    source_type=source_type,
                    source_name=source_name,
                    source_chat_id=source_chat_id,
                    source_message_id=source_message_id,
                    remind_before_minutes=candidate.get("remind_before_minutes"),
                )
                if event:
                    created.append(event)
        return created
    except Exception as exc:
        logger.debug("Userbot calendar extraction failed for user {}: {}", user_id, exc)
        return []


async def _create_followup_event(
    *,
    user_id: int,
    classification: dict,
    sender_name: str,
    summary: str,
    source_type: str,
    source_chat_id: int | None,
    source_message_id: int | None,
):
    """Create a "reply by <time>" calendar event when a deadline was detected."""
    try:
        if not _classification_requires_response(classification):
            return None
        followup_at = classification.get("suggested_followup_at")
        if not isinstance(followup_at, datetime):
            return None

        from ..db import get_session
        from .calendar_service import CalendarService

        async with get_session() as session:
            return await CalendarService.create_event(
                session,
                user_id=user_id,
                title=f"Ответить: {sender_name}",
                starts_at=followup_at,
                description=summary,
                source_type=source_type,
                source_name=sender_name,
                source_chat_id=source_chat_id,
                source_message_id=source_message_id,
                remind_before_minutes=30,
            )
    except Exception as exc:
        logger.debug(
            "Userbot follow-up calendar event failed for user {}: {}", user_id, exc
        )
        return None


async def _format_calendar_lines(user_id: int, calendar_events: list) -> str:
    if not calendar_events:
        return ""
    tzname = await _get_user_timezone(user_id)
    from .calendar_service import format_local

    lines = []
    for event in calendar_events:
        lines.append(
            f"📅 <b>Добавила в календарь:</b> {_esc(event.title)} — "
            f"{format_local(event.starts_at, tzname)}"
        )
    return "\n".join(lines)


async def _get_user_timezone(user_id: int) -> str:
    try:
        from ..db import get_session
        from ..models.users import User

        async with get_session() as session:
            user = await session.get(User, user_id)
            if user and user.user_timezone:
                return user.user_timezone
    except Exception as exc:
        logger.debug("Userbot: timezone lookup failed for user {}: {}", user_id, exc)
    return "UTC"


# ---------------------------------------------------------------------------
# Message burst batching
# ---------------------------------------------------------------------------


def _reply_batch_delay_seconds() -> float:
    return float(
        max(
            1,
            app_settings.USERBOT_READ_CHECK_DELAY_SECONDS,
            app_settings.USERBOT_REPLY_DEBOUNCE_SECONDS,
        )
    )


def _reply_batch_key(
    *,
    user_id: int,
    chat_id: int,
    sender_tg_id: int,
    chat_type: str,
) -> str:
    return f"ub_reply_batch:{user_id}:{chat_type}:{chat_id}:{sender_tg_id}"


def _reply_batch_version_key(batch_key: str) -> str:
    return f"{batch_key}:version"


async def _enqueue_reply_batch_message(
    *,
    user_id: int,
    chat_id: int,
    sender_tg_id: int,
    chat_type: str,
    message_id: int,
    text: str,
) -> tuple[str, int]:
    batch_key = _reply_batch_key(
        user_id=user_id,
        chat_id=chat_id,
        sender_tg_id=sender_tg_id,
        chat_type=chat_type,
    )
    version_key = _reply_batch_version_key(batch_key)
    entry = json.dumps(
        {
            "message_id": message_id,
            "text": text[:1200],
            "ts": int(time.time()),
        },
        ensure_ascii=False,
    )
    redis = await _get_redis()
    try:
        ttl_seconds = int(_reply_batch_delay_seconds()) + 120
        async with redis.pipeline(transaction=True) as pipe:
            pipe.rpush(batch_key, entry)
            pipe.expire(batch_key, ttl_seconds)
            pipe.incr(version_key)
            pipe.expire(version_key, ttl_seconds)
            result = await pipe.execute()
        return batch_key, int(result[2])
    finally:
        await redis.aclose()


async def _drain_reply_batch_if_current(
    *,
    batch_key: str,
    expected_version: int,
) -> list[dict] | None:
    version_key = _reply_batch_version_key(batch_key)
    script = """
    if redis.call('GET', KEYS[2]) == ARGV[1] then
        local items = redis.call('LRANGE', KEYS[1], 0, -1)
        redis.call('DEL', KEYS[1], KEYS[2])
        return items
    end
    return nil
    """
    redis = await _get_redis()
    try:
        raw_items = await redis.eval(
            script, 2, batch_key, version_key, str(expected_version)
        )
    finally:
        await redis.aclose()

    if raw_items is None:
        return None

    messages: list[dict] = []
    for raw in raw_items:
        try:
            item = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        messages.append(
            {
                "message_id": _coerce_int(item.get("message_id")) or 0,
                "text": text,
                "ts": _coerce_int(item.get("ts")) or 0,
            }
        )
    return messages


def _latest_batch_message_id(messages: list[dict], fallback: int) -> int:
    message_ids = [
        message_id
        for message in messages
        if (message_id := _coerce_int(message.get("message_id"))) is not None
    ]
    return max(message_ids) if message_ids else fallback


def _latest_batch_ts(messages: list[dict]) -> int:
    timestamps = [
        ts for message in messages if (ts := _coerce_int(message.get("ts"))) is not None
    ]
    return max(timestamps) if timestamps else 0


def _batch_message_text(messages: list[dict]) -> str:
    texts = [str(item.get("text") or "").strip() for item in messages]
    texts = [text for text in texts if text]
    if not texts:
        return ""
    if len(texts) == 1:
        return texts[0]
    return "\n".join(f"{index}. {text}" for index, text in enumerate(texts, 1))


def _batch_preview(messages: list[dict], *, fallback: str, limit: int = 400) -> str:
    text = _batch_message_text(messages) or fallback
    compact = _short_summary(text, limit)
    if len(messages) > 1:
        return f"{len(messages)} messages:\n{compact}"
    return compact


async def _check_group_notification_rate_limit(user_id: int, chat_id: int) -> bool:
    today_str = date.today().isoformat()
    rate_key = f"userbot_group_notif:{user_id}:{chat_id}:{today_str}"
    redis = await _get_redis()
    try:
        async with redis.pipeline(transaction=True) as pipe:
            pipe.incr(rate_key)
            pipe.execute_command("EXPIRE", rate_key, 90_000, "NX")
            pipe_result = await pipe.execute()
        count = int(pipe_result[0])
        return count <= app_settings.USERBOT_MAX_GROUP_NOTIFS_PER_DAY
    finally:
        await redis.aclose()


# ---------------------------------------------------------------------------
# Manual outgoing tracking
# ---------------------------------------------------------------------------


async def _record_manual_outgoing(
    *,
    user_id: int,
    chat_id: int,
    message_id: int | None,
) -> None:
    from .userbot_state_probe import cache_manual_outgoing

    await cache_manual_outgoing(
        user_id=user_id,
        chat_id=chat_id,
        message_id=message_id,
    )


async def _has_manual_outgoing_after(
    *,
    user_id: int,
    chat_id: int,
    message_id: int,
    message_ts: int = 0,
) -> bool:
    return await has_cached_manual_outgoing_after(
        user_id=user_id,
        chat_id=chat_id,
        message_id=message_id,
        message_ts=message_ts,
    )


# ---------------------------------------------------------------------------
# Persistent thread tracking integration
# ---------------------------------------------------------------------------


async def _classify_incoming_message(
    *,
    user_id: int,
    text: str,
    sender_name: str,
    chat_type: str,
    conversation_thread: list[dict],
) -> dict:
    """Return summary/importance metadata for durable userbot thread storage."""
    try:
        from .userbot_thread_service import UserBotThreadService

        service = UserBotThreadService()
        result = await service.classify_message(
            chat_type=chat_type,
            sender_name=sender_name,
            message_text=text,
            conversation_summary=_thread_summary(conversation_thread),
        )
        if isinstance(result, dict):
            result.setdefault("message_summary", _short_summary(text))
            result["summary"] = result.get("message_summary") or _short_summary(text)
            return result
    except Exception as exc:
        logger.debug("Userbot thread classifier failed for user {}: {}", user_id, exc)

    return {
        "classification_available": False,
        "summary": _short_summary(text),
        "importance": 1,
        "requires_response": False,
        "suggested_followup_at": None,
        "memory_worthy": False,
        "memory_items": [],
        "chat_type": chat_type,
    }


def _classification_available(classification: dict) -> bool:
    return classification.get("classification_available", True) is not False


def _classification_requires_response(classification: dict) -> bool:
    raw = classification.get("requires_response", False)
    if isinstance(raw, str):
        return raw.strip().lower() not in {"false", "0", "no", "нет"}
    return bool(raw)


def _classification_importance(classification: dict) -> int:
    try:
        return max(1, min(5, int(classification.get("importance", 1) or 1)))
    except (TypeError, ValueError):
        return 1


async def _persist_incoming_thread(
    *,
    user_id: int,
    chat_id: int,
    message_id: int,
    sender_name: str,
    sender_tg_id: int,
    chat_type: str,
    message_text: str,
    summary: str,
    classification: dict,
) -> int | None:
    """Persist an incoming DM/group prompt through the thread service."""
    try:
        from ..db import get_session
        from .userbot_thread_service import UserBotThreadService

        async with get_session() as session:
            service = UserBotThreadService()
            thread = await service.create_or_update_incoming(
                session=session,
                user_id=user_id,
                chat_id=chat_id,
                chat_type=chat_type,
                sender_tg_id=sender_tg_id,
                sender_name=sender_name,
                message_id=message_id,
                message_text=message_text,
                suggested_replies=[],
                classification={
                    **classification,
                    "message_summary": classification.get("message_summary")
                    or classification.get("summary")
                    or summary,
                },
            )
            return getattr(thread, "id", None)
    except TypeError as exc:
        logger.debug("Userbot thread service signature mismatch: {}", exc)
    except Exception as exc:
        logger.debug("Userbot thread persistence failed for user {}: {}", user_id, exc)
    return None


async def _attach_thread_notification(
    *,
    user_id: int,
    thread_id: int | None,
    notification_chat_id: int | None,
    notification_message_id: int | None,
) -> None:
    try:
        from ..db import get_session
        from .userbot_thread_service import UserBotThreadService

        async with get_session() as session:
            service = UserBotThreadService()
            await service.attach_notification(
                session,
                user_id=user_id,
                thread_id=thread_id,
                notification_chat_id=notification_chat_id,
                notification_message_id=notification_message_id,
            )
    except Exception as exc:
        logger.debug(
            "Userbot notification tracking failed for user {} thread {}: {}",
            user_id,
            thread_id,
            exc,
        )


async def _clear_read_thread_notifications(
    *,
    user_id: int,
    chat_id: int,
    max_read_message_id: int,
    bot: Bot,
) -> None:
    try:
        from ..db import get_session
        from .userbot_thread_service import UserBotThreadService

        async with get_session() as session:
            service = UserBotThreadService()
            cleanup_targets = await service.clear_notifications_for_read(
                session,
                user_id=user_id,
                chat_id=chat_id,
                max_read_message_id=max_read_message_id,
            )
    except Exception as exc:
        logger.debug(
            "Userbot read notification cleanup failed for user {} chat {}: {}",
            user_id,
            chat_id,
            exc,
        )
        return

    for cleanup_target in cleanup_targets:
        await _cleanup_thread_notification(
            bot=bot,
            cleanup_target=cleanup_target,
            reason="read",
        )


async def _cleanup_thread_notification(
    *,
    bot: Bot | None,
    cleanup_target: dict,
    reason: str,
) -> None:
    if not bot:
        return

    notification_chat_id = _coerce_int(cleanup_target.get("notification_chat_id"))
    notification_message_id = _coerce_int(cleanup_target.get("notification_message_id"))
    if not notification_chat_id or not notification_message_id:
        return

    try:
        await bot.delete_message(notification_chat_id, notification_message_id)
    except Exception as exc:
        logger.debug(
            "Userbot notification delete failed for chat {} message {} ({}): {}",
            notification_chat_id,
            notification_message_id,
            reason,
            exc,
        )
        try:
            await bot.edit_message_reply_markup(
                chat_id=notification_chat_id,
                message_id=notification_message_id,
                reply_markup=None,
            )
        except Exception as fallback_exc:
            logger.debug(
                "Userbot notification markup cleanup failed for chat {} message {}: {}",
                notification_chat_id,
                notification_message_id,
                fallback_exc,
            )


async def _mark_latest_thread_replied(
    *,
    user_id: int,
    chat_id: int,
    message_id: int | None,
    chat_type: str | None,
    reply_to_message_id: int | None,
) -> dict | None:
    """Mark the latest open thread in this chat as replied after a real outgoing message."""
    try:
        from ..db import get_session
        from .userbot_thread_service import UserBotThreadService

        async with get_session() as session:
            service = UserBotThreadService()
            return await service.mark_replied_by_outgoing(
                session,
                user_id=user_id,
                chat_id=chat_id,
                message_id=message_id,
                chat_type=chat_type,
                reply_to_message_id=reply_to_message_id,
            )
    except TypeError as exc:
        logger.debug("Userbot replied marker signature mismatch: {}", exc)
    except Exception as exc:
        logger.debug("Userbot replied marker failed for user {}: {}", user_id, exc)
    return None


def _short_summary(text: str, limit: int = 160) -> str:
    """Short, display-safe fallback summary; raw message text stays encrypted in DB."""
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def _thread_summary(conversation_thread: list[dict], limit: int = 800) -> str:
    lines = []
    for msg in conversation_thread[-6:]:
        name = "ME" if msg.get("is_me") else msg.get("name", "?")
        text = _short_summary(str(msg.get("text", "")), 120)
        if text:
            lines.append(f"{name}: {text}")
    return "\n".join(lines)[-limit:] if lines else ""


# ===========================================================================
# Context assembly
# ===========================================================================


async def _fetch_conversation_thread(
    client: TelegramClient, chat_id: int
) -> list[dict]:
    """
    Fetch the last N messages from a chat via Telethon.
    Returns a list of dicts: [{sender_id, name, text, is_me}].
    Most recent message first → reversed to chronological order.
    """
    limit = app_settings.USERBOT_THREAD_FETCH_LIMIT
    try:
        me = await client.get_me()
        messages = await client.get_messages(chat_id, limit=limit)
        thread = []
        for msg in reversed(messages):  # chronological order
            if not msg.message:
                continue
            sender = await msg.get_sender()
            first = getattr(sender, "first_name", None) or ""
            last = getattr(sender, "last_name", None) or ""
            name = f"{first} {last}".strip() or getattr(sender, "username", None) or "?"
            thread.append(
                {
                    "sender_id": msg.sender_id,
                    "name": name,
                    "text": msg.message[:300],
                    "is_me": msg.sender_id == me.id,
                }
            )
        return thread
    except Exception as exc:
        logger.debug(
            "Failed to fetch conversation thread for chat {}: {}", chat_id, exc
        )
        return []


async def _get_user_core_facts(user_id: int) -> list[str]:
    """Load all core memory facts for a user from the database."""
    try:
        from ..db import get_session
        from ..models.core_memory import CoreMemory, CoreFact
        from ..models.users import User
        from sqlmodel import select

        async with get_session() as session:
            # Also fetch user profile info
            user = await session.get(User, user_id)
            facts: list[str] = []
            if user:
                if user.name:
                    facts.append(f"Name: {user.name}")
                if user.occupation_json:
                    occ = user.occupation_json
                    if isinstance(occ, dict) and occ.get("title"):
                        facts.append(f"Occupation: {occ['title']}")
                    elif isinstance(occ, str):
                        facts.append(f"Occupation: {occ}")

            # Fetch core facts
            stmt = (
                select(CoreFact)
                .join(CoreMemory, CoreMemory.id == CoreFact.core_memory_id)
                .where(CoreMemory.user_id == user_id)
            )
            result = await session.execute(stmt)
            for fact in result.scalars().all():
                facts.append(fact.fact_text)

            return facts
    except Exception as exc:
        logger.debug("Failed to load core facts for user {}: {}", user_id, exc)
        return []


# ===========================================================================
# LLM helpers
# ===========================================================================


async def _classify_post_relevance(
    text: str,
    interests: str,
    user_facts: list[str],
) -> dict:
    """
    Classify a channel post on a 1-5 relevance scale using rich user context.

    Returns dict with keys:
      score   – int 1-5 (1=irrelevant, 5=must-see)
      summary – one-line summary of the post
      reason  – why this is relevant (only meaningful for score >= 4)
    """
    _default = {"score": 1, "summary": "", "reason": ""}
    try:
        # Build user context block
        context_parts = [f"User interests: {interests}"]
        if user_facts:
            facts_block = "; ".join(user_facts[:15])
            context_parts.append(f"User profile facts: {facts_block}")

        user_context = "\n".join(context_parts)

        response = await async_client.chat.completions.create(
            model=app_settings.EXTRACTOR_MODEL_ID,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a personal content relevance classifier.\n"
                        "Given a user profile and a channel post, output EXACTLY 3 lines:\n"
                        "Line 1: relevance score 1-5 (1=irrelevant, 2=marginally relevant, "
                        "3=somewhat interesting, 4=important, 5=must-see)\n"
                        "Line 2: one-sentence summary of the post (max 100 chars)\n"
                        "Line 3: why this matters to THIS user (max 80 chars, "
                        "or 'N/A' if score < 4)\n"
                        "No extra text, no labels, no formatting."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"<user_context>\n{user_context}\n</user_context>\n\n"
                        f"<channel_post>\n{text[:1500]}\n</channel_post>"
                    ),
                },
            ],
            max_tokens=120,
            temperature=0,
        )
        raw = (response.choices[0].message.content or "").strip()
        lines = [line.strip() for line in raw.splitlines() if line.strip()]

        if not lines:
            return _default

        # Parse score from first line
        score_match = re.search(r"\d", lines[0])
        score = int(score_match.group()) if score_match else 1
        score = max(1, min(5, score))

        summary = lines[1] if len(lines) > 1 else ""
        reason = lines[2] if len(lines) > 2 else ""
        if reason.upper().strip() == "N/A":
            reason = ""

        return {"score": score, "summary": summary, "reason": reason}

    except Exception as exc:
        logger.warning("Userbot post classification LLM error: {}", exc)
        return _default


# ===========================================================================
# Channel notification formatting & batching
# ===========================================================================


def _format_high_priority_notification(
    *,
    channel_name: str,
    summary: str,
    reason: str,
    post_link: str,
) -> str:
    """Format a high-priority (score 4-5) channel notification — concise but informative."""
    parts = [f"🔥 <b>{_esc(channel_name)}</b>"]
    parts.append(f"{_esc(summary)}")
    if reason:
        parts.append(f"<i>→ {_esc(reason)}</i>")
    if post_link:
        parts.append(f"🔗 <a href='{post_link}'>Open</a>")
    return "\n".join(parts)


def _format_batch_digest(items: list[dict]) -> str:
    """Format accumulated medium-priority posts into a single compact digest."""
    if not items:
        return ""
    lines = ["📋 <b>Channel digest:</b>"]
    for item in items:
        line = f"• <b>{_esc(item['channel_name'])}</b>: {_esc(item['summary'])}"
        if item.get("post_link"):
            line += f" (<a href='{item['post_link']}'>link</a>)"
        lines.append(line)
    return "\n".join(lines)


async def _add_to_channel_batch(
    *,
    user_id: int,
    channel_name: str,
    summary: str,
    post_link: str,
    score: int,
) -> None:
    """Add a medium-relevance post to the user's batch digest in Redis."""
    entry = json.dumps(
        {
            "channel_name": channel_name,
            "summary": summary,
            "post_link": post_link,
            "score": score,
            "ts": int(time.time()),
        },
        ensure_ascii=False,
    )
    redis = await _get_redis()
    try:
        list_key = f"ub_channel_batch:{user_id}"
        await redis.rpush(list_key, entry)
        # Auto-expire the list after 24 hours as a safety net
        await redis.expire(list_key, 86_400)
    finally:
        await redis.aclose()


async def _get_channel_batch_size(user_id: int) -> int:
    redis = await _get_redis()
    try:
        return await redis.llen(f"ub_channel_batch:{user_id}")
    finally:
        await redis.aclose()


async def flush_channel_batch(user_id: int, bot: "Bot") -> None:
    """
    Flush the accumulated medium-priority channel posts as a single digest.
    Called by the auto-flush threshold in _handle_channel_post and by the
    periodic scheduler job.
    """
    user_settings = await _get_user_settings(user_id)
    if user_settings and _is_break_mode_active(user_settings):
        return

    redis = await _get_redis()
    try:
        list_key = f"ub_channel_batch:{user_id}"
        raw_items = await redis.lrange(list_key, 0, -1)
        if not raw_items:
            return
        # Atomically drain the list
        await redis.delete(list_key)
    finally:
        await redis.aclose()

    items = []
    for raw in raw_items:
        try:
            items.append(json.loads(raw))
        except (json.JSONDecodeError, TypeError):
            continue

    if not items:
        return

    # Sort by score descending so more relevant items appear first
    items.sort(key=lambda x: x.get("score", 0), reverse=True)

    digest = _format_batch_digest(items)
    tg_id, topic_kwargs = await _get_tg_delivery(user_id)
    if tg_id and digest:
        await bot.send_message(
            tg_id,
            digest,
            parse_mode="HTML",
            disable_web_page_preview=True,
            **topic_kwargs,
        )
        # Save summarized digest to conversation history
        summaries = "; ".join(f"{it['channel_name']}: {it['summary']}" for it in items)
        await _save_notification_to_history(
            tg_chat_id=tg_id,
            text=f"[Channel digest — {len(items)} posts]: {summaries}",
        )
        logger.info(
            "Userbot: flushed channel digest ({} posts) for user {}",
            len(items),
            user_id,
        )


async def _save_notification_to_history(*, tg_chat_id: int, text: str) -> None:
    """
    Save a summarized channel notification to conversation history so the LLM
    knows what the user has been informed about during proactive flows.
    """
    try:
        from .conversation_history_service import ConversationHistoryService

        await ConversationHistoryService.save_history(
            tg_chat_id,
            [{"role": "assistant", "content": text}],
        )
    except Exception as exc:
        logger.debug("Failed to save notification to history: {}", exc)


# ---------------------------------------------------------------------------
# DB / Redis helpers
# ---------------------------------------------------------------------------


async def _get_user_settings(user_id: int):
    """Return UserSettings for the given bot user_id, or None on error."""
    try:
        from ..db import get_session
        from ..models.settings import UserSettings
        from sqlmodel import select

        async with get_session() as session:
            result = await session.execute(
                select(UserSettings).where(UserSettings.user_id == user_id)
            )
            return result.scalar_one_or_none()
    except Exception as exc:
        logger.warning("Userbot: could not load settings for user {}: {}", user_id, exc)
        return None


async def _get_channel_interests(user_id: int) -> str:
    """
    Return the user's channel-interest description from UserSettings.
    Falls back to a generic description if none is set.
    """
    settings = await _get_user_settings(user_id)
    if settings and settings.userbot_channel_interests:
        return settings.userbot_channel_interests
    return "technology, science, business, current events, health"


async def _get_tg_delivery(user_id: int) -> tuple[int | None, dict[str, int]]:
    """Look up Telegram chat_id and private-topic kwargs for bot notifications."""
    try:
        from ..db import get_session
        from ..models.users import User

        async with get_session() as session:
            user = await session.get(User, user_id)
            if not user:
                return None, {}
            return user.tg_chat_id, topic_kwargs_for_user(user)
    except Exception as exc:
        logger.error(
            "Userbot: could not fetch tg_chat_id for user {}: {}", user_id, exc
        )
        return None, {}


async def _get_redis():
    from redis.asyncio import Redis

    return Redis.from_url(app_settings.REDIS_URL)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def _event_sender_id(event) -> int | None:
    sender_id = getattr(event, "sender_id", None)
    if sender_id is None:
        sender_id = getattr(getattr(event, "message", None), "sender_id", None)
    return _coerce_int(sender_id)


def _event_chat_id(event) -> int | None:
    return _coerce_int(getattr(event, "chat_id", None))


def _coerce_int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _ids_equal(left, right) -> bool:
    left_int = _coerce_int(left)
    right_int = _coerce_int(right)
    return left_int is not None and right_int is not None and left_int == right_int


def _is_outgoing_event(event) -> bool:
    message = getattr(event, "message", None)
    return bool(getattr(event, "out", False) or getattr(message, "out", False))


def _reply_to_message_id(event) -> int | None:
    message = getattr(event, "message", None)
    reply_to = getattr(message, "reply_to", None)
    return _coerce_int(getattr(reply_to, "reply_to_msg_id", None))


def _is_private_chat_with_telegram_id(event, telegram_id: int | None) -> bool:
    return bool(
        telegram_id is not None
        and getattr(event, "is_private", False)
        and _ids_equal(_event_chat_id(event), telegram_id)
    )


def _should_ignore_assistant_bot_event(event, assistant_bot_id: int | None) -> bool:
    if assistant_bot_id is None:
        return False
    return _ids_equal(
        _event_sender_id(event), assistant_bot_id
    ) or _is_private_chat_with_telegram_id(event, assistant_bot_id)


def _is_telegram_bot_sender(sender) -> bool:
    return bool(getattr(sender, "bot", False))


def _esc(text: str) -> str:
    """Escape HTML special characters for Telegram HTML parse mode."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
