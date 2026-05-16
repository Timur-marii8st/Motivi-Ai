"""
UserBotMonitor — Telethon event handlers and LLM-powered notification logic.

Four types of events are handled:
  1. New posts in channels the user is subscribed to.
     → An LLM classifies whether the post is relevant to the user's interests.
       If yes, a formatted notification is sent via the bot.
  2. Incoming private messages (DMs) to the user's personal account.
     → The LLM suggests 3 reply options written in the user's personal style.
       A formatted notification with approval buttons is sent via the bot.
  3. Incoming group/supergroup messages mentioning the user or replying to them.
     → Same as DMs: LLM suggests replies with approval buttons.
  4. Outgoing messages from the user (DMs and groups).
     → Stored as communication style samples so the LLM can mimic the user.

Context assembly for reply suggestions
---------------------------------------
Before generating suggestions the monitor gathers:
  • Conversation thread — last N messages from the chat (via Telethon).
  • User profile — core memory facts (personality, occupation, interests).
  • Communication style — recent outgoing messages the user actually typed.
  • Sender relationship — cached LLM-inferred description of who the sender is.

Safety guarantees
-----------------
* Telethon write operations (send_message, send_chat_action) are ONLY called
  after explicit user approval via bot callback buttons (human-in-the-loop).
* Human-like delays and typing simulation are applied before sending.
* Rate limiting via Redis prevents notification and reply floods.
* All pending replies expire after USERBOT_REPLY_TIMEOUT seconds.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from loguru import logger
from telethon import TelegramClient, events

from ..config import settings as app_settings
from ..llm.client import async_client
from ..utils.telegram_topics import topic_kwargs_for_user

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
            logger.debug("Could not resolve aiogram bot id for userbot filters: {}", exc)
        return assistant_bot_id

    @client.on(events.NewMessage(incoming=True, func=lambda e: e.is_channel and not e.is_group))
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

    # Learn communication style from the user's own outgoing messages
    @client.on(events.NewMessage(outgoing=True, func=lambda e: e.is_private or e.is_group))
    async def on_outgoing(event):
        await _handle_outgoing_message(
            event,
            user_id,
            assistant_bot_id=await resolve_assistant_bot_id(),
        )


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
            post_link = (
                f"https://t.me/{channel_username}/{event.message.id}"
            )

        tg_id, topic_kwargs = await _get_tg_delivery(user_id)
        if not tg_id:
            return

        # HIGH relevance → send immediately with detail
        if score >= app_settings.USERBOT_CHANNEL_HIGH_THRESHOLD:
            reason = classification.get("reason", "")
            notification = _format_high_priority_notification(
                channel_name=channel_name,
                summary=summary,
                reason=reason,
                post_link=post_link,
            )
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
                user_id, channel_name, score,
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
# Outgoing message handler — style learning
# ---------------------------------------------------------------------------

async def _handle_outgoing_message(
    event,
    user_id: int,
    *,
    assistant_bot_id: int | None = None,
) -> None:
    """
    Collect the user's own outgoing messages as communication style samples.
    Stored in a Redis ring buffer (LPUSH + LTRIM).
    Bot-sent replies are filtered out via a short-lived skip marker.
    """
    try:
        if _is_private_chat_with_telegram_id(event, assistant_bot_id):
            return

        text: str = event.message.message or ""
        if not text.strip() or len(text) < 5:
            return

        # Skip bot-sent replies (marked by _send_reply_with_human_simulation)
        redis = await _get_redis()
        try:
            skip_key = f"ub_skip_outgoing:{user_id}:{event.chat_id}"
            if await redis.get(skip_key):
                return

            # Store as style sample: JSON with text and timestamp
            sample = json.dumps(
                {"text": text[:500], "ts": int(time.time())},
                ensure_ascii=False,
            )
            list_key = f"ub_style:{user_id}"
            async with redis.pipeline(transaction=True) as pipe:
                pipe.lpush(list_key, sample)
                pipe.ltrim(list_key, 0, app_settings.USERBOT_STYLE_SAMPLES_MAX - 1)
                await pipe.execute()
        finally:
            await redis.aclose()

        await _mark_latest_thread_replied(
            user_id=user_id,
            chat_id=event.chat_id,
            message_id=event.message.id,
            reply_text=text,
        )

    except Exception as exc:
        logger.debug("Userbot outgoing handler error (user {}): {}", user_id, exc)


# ---------------------------------------------------------------------------
# DM handler — with approval buttons
# ---------------------------------------------------------------------------

async def _handle_dm(
    event,
    user_id: int,
    bot: "Bot",
    client: TelegramClient,
    *,
    assistant_bot_id: int | None = None,
) -> None:
    try:
        if _is_outgoing_event(event) or _should_ignore_assistant_bot_event(
            event, assistant_bot_id
        ):
            return

        user_settings = await _get_user_settings(user_id)
        if user_settings and not user_settings.enable_dm_notifications:
            return
        if user_settings and _is_break_mode_active(user_settings):
            return

        text: str = event.message.message or ""
        if not text.strip():
            return

        sender = await event.get_sender()
        if _is_telegram_bot_sender(sender):
            return

        first = getattr(sender, "first_name", None) or ""
        last = getattr(sender, "last_name", None) or ""
        sender_name = f"{first} {last}".strip() or getattr(sender, "username", None) or "Someone"
        sender_tg_id = getattr(sender, "id", 0)

        # Gather context in parallel for high-quality reply suggestions
        thread_coro = _fetch_conversation_thread(client, event.chat_id)
        facts_coro = _get_user_core_facts(user_id)
        style_coro = _get_style_samples(user_id)
        relationship_coro = _get_sender_relationship(user_id, sender_tg_id)

        thread, facts, style_samples, relationship = await asyncio.gather(
            thread_coro, facts_coro, style_coro, relationship_coro,
            return_exceptions=True,
        )
        # Gracefully handle failures in context fetching
        if isinstance(thread, BaseException):
            logger.debug("Thread fetch failed for user {}: {}", user_id, thread)
            thread = []
        if isinstance(facts, BaseException):
            logger.debug("Facts fetch failed for user {}: {}", user_id, facts)
            facts = []
        if isinstance(style_samples, BaseException):
            logger.debug("Style fetch failed for user {}: {}", user_id, style_samples)
            style_samples = []
        if isinstance(relationship, BaseException):
            logger.debug("Relationship fetch failed for user {}: {}", user_id, relationship)
            relationship = None

        suggestions = await _generate_reply_suggestions(
            user_id=user_id,
            message_text=text,
            sender_name=sender_name,
            sender_tg_id=sender_tg_id,
            conversation_thread=thread,
            user_facts=facts,
            style_samples=style_samples,
            sender_relationship=relationship,
        )

        classification = await _classify_incoming_message(
            user_id=user_id,
            text=text,
            sender_name=sender_name,
            chat_type="dm",
            conversation_thread=thread,
        )
        summary = classification.get("summary") or _short_summary(text)
        thread_id = await _persist_incoming_thread(
            user_id=user_id,
            chat_id=event.chat_id,
            message_id=event.message.id,
            sender_name=sender_name,
            sender_tg_id=sender_tg_id,
            chat_type="dm",
            message_text=text,
            summary=summary,
            classification=classification,
            suggestions=suggestions,
        )

        action_plan = None
        if app_settings.USERBOT_ACTION_PLAN_ENABLED:
            target_candidates = await _fetch_action_target_candidates(
                client=client,
                event=event,
                sender=sender,
                sender_name=sender_name,
                assistant_bot_id=assistant_bot_id,
            )
            action_plan = await _generate_action_plan(
                user_id=user_id,
                message_text=text,
                sender_name=sender_name,
                chat_type="dm",
                conversation_thread=thread,
                user_facts=facts,
                style_samples=style_samples,
                target_candidates=target_candidates,
            )

        preview = text[:400].strip()
        if len(text) > 400:
            preview += "…"

        notification = (
            f"💬 <b>New message from {_esc(sender_name)}:</b>\n"
            f"━━━━━━━━━━━━\n"
            f"<i>{_esc(preview)}</i>\n"
            f"━━━━━━━━━━━━\n"
            f"💡 <b>Suggested replies:</b>\n"
        )
        for i, s in enumerate(suggestions, 1):
            notification += f"{i}️⃣ {_esc(s)}\n"
        if action_plan:
            notification += _format_action_plan_for_notification(action_plan)

        # Determine if we show approval buttons
        show_buttons = user_settings and user_settings.enable_reply_approval if user_settings else True

        tg_id, topic_kwargs = await _get_tg_delivery(user_id)
        if not tg_id:
            return

        if show_buttons:
            # Store pending reply in Redis
            pending_key = await _store_pending_reply(
                user_id=user_id,
                chat_id=event.chat_id,
                message_id=event.message.id,
                sender_name=sender_name,
                sender_tg_id=sender_tg_id,
                chat_type="dm",
                suggestions=suggestions,
                thread_id=thread_id,
            )
            if action_plan:
                action_plan["user_id"] = user_id
                action_plan["reply_pending_key"] = pending_key
                action_plan["thread_id"] = thread_id
                action_plan["source_chat_id"] = event.chat_id
                action_plan["source_message_id"] = event.message.id
                action_plan["suggestions"] = suggestions
                action_plan["owner_tg_chat_id"] = tg_id
                action_plan["notification_text"] = notification
                await _store_pending_action_plan(
                    pending_key=pending_key,
                    action_plan=action_plan,
                )

            keyboard = build_userbot_approval_keyboard(
                pending_key,
                len(suggestions),
                action_plan=action_plan,
            )
            await bot.send_message(
                tg_id,
                notification,
                parse_mode="HTML",
                reply_markup=keyboard,
                **topic_kwargs,
            )
        else:
            await bot.send_message(tg_id, notification, parse_mode="HTML", **topic_kwargs)

        logger.info(
            "Userbot: sent DM notification to user {} from {}", user_id, sender_name
        )
    except Exception as exc:
        logger.error("Userbot DM handler error (user {}): {}", user_id, exc)


# ---------------------------------------------------------------------------
# Group message handler — with approval buttons
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
    Handle incoming group/supergroup messages.
    Only react to messages that mention the user or reply to the user's messages.
    """
    try:
        if _is_outgoing_event(event) or _should_ignore_assistant_bot_event(
            event, assistant_bot_id
        ):
            return

        user_settings = await _get_user_settings(user_id)
        if user_settings and not user_settings.enable_group_monitoring:
            return
        if user_settings and _is_break_mode_active(user_settings):
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

        first = getattr(sender, "first_name", None) or ""
        last = getattr(sender, "last_name", None) or ""
        sender_name = f"{first} {last}".strip() or getattr(sender, "username", None) or "Someone"
        sender_tg_id = getattr(sender, "id", 0)

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

        # Rate limit group notifications
        today_str = date.today().isoformat()
        rate_key = f"userbot_group_notif:{user_id}:{event.chat_id}:{today_str}"
        redis = await _get_redis()
        try:
            async with redis.pipeline(transaction=True) as pipe:
                pipe.incr(rate_key)
                pipe.execute_command("EXPIRE", rate_key, 90_000, "NX")
                pipe_result = await pipe.execute()
            count = int(pipe_result[0])
            if count > app_settings.USERBOT_MAX_GROUP_NOTIFS_PER_DAY:
                return
        finally:
            await redis.aclose()

        chat = await event.get_chat()
        chat_title = getattr(chat, "title", None) or f"group {event.chat_id}"

        # Gather context in parallel
        thread_coro = _fetch_conversation_thread(client, event.chat_id)
        facts_coro = _get_user_core_facts(user_id)
        style_coro = _get_style_samples(user_id)
        relationship_coro = _get_sender_relationship(user_id, sender_tg_id)

        thread, facts, style_samples, relationship = await asyncio.gather(
            thread_coro, facts_coro, style_coro, relationship_coro,
            return_exceptions=True,
        )
        if isinstance(thread, BaseException):
            thread = []
        if isinstance(facts, BaseException):
            facts = []
        if isinstance(style_samples, BaseException):
            style_samples = []
        if isinstance(relationship, BaseException):
            relationship = None

        suggestions = await _generate_reply_suggestions(
            user_id=user_id,
            message_text=text,
            sender_name=sender_name,
            sender_tg_id=sender_tg_id,
            conversation_thread=thread,
            user_facts=facts,
            style_samples=style_samples,
            sender_relationship=relationship,
        )

        classification = await _classify_incoming_message(
            user_id=user_id,
            text=text,
            sender_name=sender_name,
            chat_type="group",
            conversation_thread=thread,
        )
        summary = classification.get("summary") or _short_summary(text)
        thread_id = await _persist_incoming_thread(
            user_id=user_id,
            chat_id=event.chat_id,
            message_id=event.message.id,
            sender_name=sender_name,
            sender_tg_id=sender_tg_id,
            chat_type="group",
            message_text=text,
            summary=summary,
            classification=classification,
            suggestions=suggestions,
        )

        action_plan = None
        if app_settings.USERBOT_ACTION_PLAN_ENABLED:
            target_candidates = await _fetch_action_target_candidates(
                client=client,
                event=event,
                sender=sender,
                sender_name=sender_name,
                assistant_bot_id=assistant_bot_id,
            )
            action_plan = await _generate_action_plan(
                user_id=user_id,
                message_text=text,
                sender_name=sender_name,
                chat_type="group",
                conversation_thread=thread,
                user_facts=facts,
                style_samples=style_samples,
                target_candidates=target_candidates,
            )

        preview = text[:400].strip()
        if len(text) > 400:
            preview += "…"

        trigger = "replied to you" if is_reply_to_me else "mentioned you"
        notification = (
            f"👥 <b>{_esc(sender_name)}</b> {trigger} in <b>{_esc(chat_title)}</b>:\n"
            f"━━━━━━━━━━━━\n"
            f"<i>{_esc(preview)}</i>\n"
            f"━━━━━━━━━━━━\n"
            f"💡 <b>Suggested replies:</b>\n"
        )
        for i, s in enumerate(suggestions, 1):
            notification += f"{i}️⃣ {_esc(s)}\n"
        if action_plan:
            notification += _format_action_plan_for_notification(action_plan)

        tg_id, topic_kwargs = await _get_tg_delivery(user_id)
        if not tg_id:
            return

        show_buttons = user_settings and user_settings.enable_reply_approval if user_settings else True

        if show_buttons:
            pending_key = await _store_pending_reply(
                user_id=user_id,
                chat_id=event.chat_id,
                message_id=event.message.id,
                sender_name=sender_name,
                sender_tg_id=sender_tg_id,
                chat_type="group",
                suggestions=suggestions,
                thread_id=thread_id,
            )
            if action_plan:
                action_plan["user_id"] = user_id
                action_plan["reply_pending_key"] = pending_key
                action_plan["thread_id"] = thread_id
                action_plan["source_chat_id"] = event.chat_id
                action_plan["source_message_id"] = event.message.id
                action_plan["suggestions"] = suggestions
                action_plan["owner_tg_chat_id"] = tg_id
                action_plan["notification_text"] = notification
                await _store_pending_action_plan(
                    pending_key=pending_key,
                    action_plan=action_plan,
                )
            keyboard = build_userbot_approval_keyboard(
                pending_key,
                len(suggestions),
                action_plan=action_plan,
            )
            await bot.send_message(
                tg_id,
                notification,
                parse_mode="HTML",
                reply_markup=keyboard,
                **topic_kwargs,
            )
        else:
            await bot.send_message(tg_id, notification, parse_mode="HTML", **topic_kwargs)

        logger.info(
            "Userbot: sent group notification to user {} from {} in {}",
            user_id, sender_name, chat_title,
        )
    except Exception as exc:
        logger.error("Userbot group handler error (user {}): {}", user_id, exc)


# ---------------------------------------------------------------------------
# Approval keyboard builder
# ---------------------------------------------------------------------------

def build_userbot_approval_keyboard(
    pending_key: str,
    num_suggestions: int,
    *,
    action_plan: dict | None = None,
) -> InlineKeyboardMarkup:
    """Build inline keyboard with reply and optional action-plan approval buttons."""
    rows: list[list[InlineKeyboardButton]] = []

    # Row of suggestion buttons
    suggestion_buttons = []
    for i in range(num_suggestions):
        suggestion_buttons.append(
            InlineKeyboardButton(
                text=f"✅ #{i + 1}",
                callback_data=f"ub_send:{pending_key}:{i}",
            )
        )
    if suggestion_buttons:
        rows.append(suggestion_buttons)

    if action_plan:
        safe_pending = False
        for index, step in enumerate(action_plan.get("steps", [])):
            if step.get("status") == "done" or not _action_step_is_executable(step):
                continue

            if not step.get("requires_separate_approval"):
                safe_pending = True

            row = [
                InlineKeyboardButton(
                    text=f"▶️ Step {index + 1}",
                    callback_data=f"ub_plan_step:{pending_key}:{index}",
                )
            ]
            if _action_step_is_editable(step):
                row.append(
                    InlineKeyboardButton(
                        text=f"✏️ Edit {index + 1}",
                        callback_data=f"ub_plan_edit:{pending_key}:{index}",
                    )
                )
            rows.append(row)

        plan_row: list[InlineKeyboardButton] = []
        if safe_pending:
            plan_row.append(
                InlineKeyboardButton(
                    text="✅ Run safe steps",
                    callback_data=f"ub_plan_all:{pending_key}",
                )
            )
        plan_row.append(
            InlineKeyboardButton(
                text="🚫 Dismiss plan",
                callback_data=f"ub_plan_dismiss:{pending_key}",
            )
        )
        rows.append(plan_row)

    # Edit and dismiss row
    rows.append([
        InlineKeyboardButton(
            text="✏️ Edit",
            callback_data=f"ub_edit:{pending_key}",
        ),
        InlineKeyboardButton(
            text="🚫 Dismiss",
            callback_data=f"ub_dismiss:{pending_key}",
        ),
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def _build_approval_keyboard(pending_key: str, num_suggestions: int) -> InlineKeyboardMarkup:
    return build_userbot_approval_keyboard(pending_key, num_suggestions)


# ---------------------------------------------------------------------------
# Redis pending reply storage
# ---------------------------------------------------------------------------

async def _store_pending_reply(
    *,
    user_id: int,
    chat_id: int,
    message_id: int,
    sender_name: str,
    sender_tg_id: int,
    chat_type: str,
    suggestions: list[str],
    thread_id: int | None = None,
) -> str:
    """
    Store a pending reply in Redis and return a unique key.
    The key is used in callback_data to identify which reply to send.
    """
    # Short unique key: hash of user_id + chat_id + message_id + timestamp
    raw = f"{user_id}:{chat_id}:{message_id}:{time.time()}"
    short_hash = hashlib.sha256(raw.encode()).hexdigest()[:12]
    pending_key = short_hash

    data = {
        "user_id": user_id,
        "chat_id": chat_id,
        "message_id": message_id,
        "sender_name": sender_name,
        "sender_tg_id": sender_tg_id,
        "chat_type": chat_type,
        "suggestions": suggestions,
        "thread_id": thread_id,
    }

    redis = await _get_redis()
    try:
        redis_key = f"ub_pending:{pending_key}"
        await redis.setex(
            redis_key,
            app_settings.USERBOT_REPLY_TIMEOUT,
            json.dumps(data, ensure_ascii=False),
        )
    finally:
        await redis.aclose()

    return pending_key


async def get_pending_reply(pending_key: str) -> dict | None:
    """Retrieve a pending reply from Redis. Returns None if expired or not found."""
    redis = await _get_redis()
    try:
        raw = await redis.get(f"ub_pending:{pending_key}")
        if not raw:
            return None
        return json.loads(raw)
    finally:
        await redis.aclose()


async def delete_pending_reply(pending_key: str) -> None:
    """Remove a pending reply from Redis after it's been handled."""
    redis = await _get_redis()
    try:
        await redis.delete(f"ub_pending:{pending_key}", f"ub_action_plan:{pending_key}")
    finally:
        await redis.aclose()


async def _store_pending_action_plan(*, pending_key: str, action_plan: dict) -> None:
    """Store a pending action plan under the same key as its reply notification."""
    redis = await _get_redis()
    try:
        await redis.setex(
            f"ub_action_plan:{pending_key}",
            app_settings.USERBOT_REPLY_TIMEOUT,
            json.dumps(action_plan, ensure_ascii=False),
        )
    finally:
        await redis.aclose()


async def get_pending_action_plan(pending_key: str) -> dict | None:
    redis = await _get_redis()
    try:
        raw = await redis.get(f"ub_action_plan:{pending_key}")
        if not raw:
            return None
        return json.loads(raw)
    finally:
        await redis.aclose()


async def save_pending_action_plan(pending_key: str, action_plan: dict) -> None:
    redis = await _get_redis()
    try:
        await redis.setex(
            f"ub_action_plan:{pending_key}",
            app_settings.USERBOT_REPLY_TIMEOUT,
            json.dumps(action_plan, ensure_ascii=False),
        )
    finally:
        await redis.aclose()


async def delete_pending_action_plan(pending_key: str) -> None:
    redis = await _get_redis()
    try:
        await redis.delete(f"ub_action_plan:{pending_key}")
    finally:
        await redis.aclose()


# ---------------------------------------------------------------------------
# Reply rate limiting
# ---------------------------------------------------------------------------

async def check_reply_rate_limit(user_id: int) -> bool:
    """Return True if the user is under their daily reply limit (read-only check)."""
    today_str = date.today().isoformat()
    rate_key = f"ub_replies:{user_id}:{today_str}"

    redis = await _get_redis()
    try:
        current = await redis.get(rate_key)
        count = int(current) if current else 0
        return count < app_settings.USERBOT_MAX_REPLIES_PER_DAY
    finally:
        await redis.aclose()


async def increment_reply_counter(user_id: int) -> None:
    """Increment the daily reply counter AFTER a successful send."""
    today_str = date.today().isoformat()
    rate_key = f"ub_replies:{user_id}:{today_str}"

    redis = await _get_redis()
    try:
        async with redis.pipeline(transaction=True) as pipe:
            pipe.incr(rate_key)
            pipe.execute_command("EXPIRE", rate_key, 90_000, "NX")
            await pipe.execute()
    finally:
        await redis.aclose()


# ---------------------------------------------------------------------------
# Skip marker for bot-sent outgoing messages
# ---------------------------------------------------------------------------

async def mark_bot_sent_reply(user_id: int, chat_id: int) -> None:
    """
    Set a short-lived marker so the outgoing handler skips
    messages sent by the bot (approved replies).
    Called from userbot router after successful send.
    """
    redis = await _get_redis()
    try:
        await redis.setex(f"ub_skip_outgoing:{user_id}:{chat_id}", 15, "1")
    finally:
        await redis.aclose()


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
        "summary": _short_summary(text),
        "importance": 3,
        "requires_response": True,
        "suggested_followup_at": None,
        "memory_worthy": False,
        "memory_items": [],
        "chat_type": chat_type,
    }


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
    suggestions: list[str],
) -> int | None:
    """Persist an incoming DM/group prompt through Worker B's thread service."""
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
                suggested_replies=suggestions,
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


async def _mark_latest_thread_replied(
    *,
    user_id: int,
    chat_id: int,
    message_id: int,
    reply_text: str,
) -> None:
    """Mark the latest open thread in this chat as replied after a real outgoing message."""
    try:
        from ..db import get_session
        from .userbot_thread_service import UserBotThreadService

        async with get_session() as session:
            service = UserBotThreadService()
            await service.mark_replied_by_outgoing(
                session,
                user_id=user_id,
                chat_id=chat_id,
            )
    except TypeError as exc:
        logger.debug("Userbot replied marker signature mismatch: {}", exc)
    except Exception as exc:
        logger.debug("Userbot replied marker failed for user {}: {}", user_id, exc)


def _short_summary(text: str, limit: int = 160) -> str:
    """Short, display-safe fallback summary; raw message text stays encrypted in DB."""
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


# ===========================================================================
def _thread_summary(conversation_thread: list[dict], limit: int = 800) -> str:
    lines = []
    for msg in conversation_thread[-6:]:
        name = "ME" if msg.get("is_me") else msg.get("name", "?")
        text = _short_summary(str(msg.get("text", "")), 120)
        if text:
            lines.append(f"{name}: {text}")
    return "\n".join(lines)[-limit:] if lines else ""


# ===========================================================================
# Context assembly for reply suggestions
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
            thread.append({
                "sender_id": msg.sender_id,
                "name": name,
                "text": msg.message[:300],
                "is_me": msg.sender_id == me.id,
            })
        return thread
    except Exception as exc:
        logger.debug("Failed to fetch conversation thread for chat {}: {}", chat_id, exc)
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


async def _get_style_samples(user_id: int) -> list[str]:
    """Retrieve the user's outgoing message samples from Redis."""
    redis = await _get_redis()
    try:
        raw_list = await redis.lrange(f"ub_style:{user_id}", 0, -1)
        samples = []
        for raw in raw_list:
            try:
                entry = json.loads(raw)
                samples.append(entry["text"])
            except (json.JSONDecodeError, KeyError):
                continue
        return samples
    finally:
        await redis.aclose()


async def _get_sender_relationship(user_id: int, sender_tg_id: int) -> str | None:
    """Get cached sender relationship description from Redis."""
    redis = await _get_redis()
    try:
        raw = await redis.get(f"ub_sender:{user_id}:{sender_tg_id}")
        return raw.decode() if raw else None
    finally:
        await redis.aclose()


async def _update_sender_relationship(
    user_id: int, sender_tg_id: int, description: str
) -> None:
    """Cache the LLM-inferred sender relationship in Redis."""
    redis = await _get_redis()
    try:
        await redis.setex(
            f"ub_sender:{user_id}:{sender_tg_id}",
            app_settings.USERBOT_SENDER_CACHE_TTL,
            description,
        )
    finally:
        await redis.aclose()


# ---------------------------------------------------------------------------
# Action-plan context and validation
# ---------------------------------------------------------------------------

async def _fetch_action_target_candidates(
    *,
    client: TelegramClient,
    event,
    sender,
    sender_name: str,
    assistant_bot_id: int | None,
) -> list[dict]:
    """
    Build an allowlist of private chats the action planner may target.
    The LLM only receives refs; executable steps are accepted only if the ref
    maps back to one of these candidates.
    """
    candidates: list[dict] = []
    seen_chat_ids: set[int] = set()

    def add_candidate(*, ref: str, label: str, chat_id: int, username: str | None = None) -> None:
        if _ids_equal(chat_id, assistant_bot_id) or chat_id in seen_chat_ids:
            return
        clean_label = _short_summary(label, 80)
        if not clean_label:
            return
        seen_chat_ids.add(chat_id)
        candidates.append(
            {
                "ref": ref,
                "label": clean_label,
                "chat_id": chat_id,
                "username": username,
            }
        )

    sender_id = _coerce_int(getattr(sender, "id", None))
    if sender_id and not _is_telegram_bot_sender(sender):
        sender_username = getattr(sender, "username", None)
        target_chat_id = _event_chat_id(event) if getattr(event, "is_private", False) else sender_id
        if target_chat_id:
            add_candidate(
                ref="sender",
                label=sender_name,
                chat_id=target_chat_id,
                username=sender_username,
            )

    try:
        limit = max(0, app_settings.USERBOT_ACTION_TARGET_DIALOG_LIMIT)
        index = 1
        async for dialog in client.iter_dialogs(limit=limit):
            if not getattr(dialog, "is_user", False):
                continue
            entity = getattr(dialog, "entity", None)
            if not entity or _is_telegram_bot_sender(entity):
                continue

            chat_id = _coerce_int(getattr(dialog, "id", None) or getattr(entity, "id", None))
            if not chat_id:
                continue
            first = getattr(entity, "first_name", None) or ""
            last = getattr(entity, "last_name", None) or ""
            label = (
                f"{first} {last}".strip()
                or getattr(entity, "username", None)
                or getattr(dialog, "name", None)
                or f"user {chat_id}"
            )
            add_candidate(
                ref=f"contact_{index}",
                label=label,
                chat_id=chat_id,
                username=getattr(entity, "username", None),
            )
            index += 1
    except Exception as exc:
        logger.debug("Userbot action target fetch failed: {}", exc)

    return candidates[: app_settings.USERBOT_ACTION_TARGET_DIALOG_LIMIT + 1]


def _action_target_prompt(candidates: list[dict]) -> str:
    if not candidates:
        return "No contact targets are safely resolvable."
    lines = []
    for candidate in candidates[: app_settings.USERBOT_ACTION_TARGET_DIALOG_LIMIT + 1]:
        username = candidate.get("username")
        suffix = f" (@{username})" if username else ""
        lines.append(f"- {candidate['ref']}: {candidate['label']}{suffix}")
    return "\n".join(lines)


async def _generate_action_plan(
    *,
    user_id: int,
    message_text: str,
    sender_name: str,
    chat_type: str,
    conversation_thread: list[dict],
    user_facts: list[str],
    style_samples: list[str],
    target_candidates: list[dict],
) -> dict | None:
    """
    Ask the LLM for an optional multi-step action draft and validate it.
    Returns None when a single reply is enough or the draft is unsafe.
    """
    try:
        context_parts = [
            f"Current UTC time: {datetime.now(timezone.utc).isoformat()}",
            f"Chat type: {chat_type}",
            f"Current sender: {sender_name}",
            "Allowed contact target refs:\n" + _action_target_prompt(target_candidates),
        ]
        if user_facts:
            context_parts.append("User facts:\n" + "\n".join(f"- {f}" for f in user_facts[:12]))
        if style_samples:
            context_parts.append(
                "Recent user writing style:\n"
                + "\n".join(f"- {sample}" for sample in style_samples[:8])
            )
        if conversation_thread:
            context_parts.append("Conversation:\n" + _thread_summary(conversation_thread, limit=1200))

        response = await async_client.chat.completions.create(
            model=app_settings.EXTRACTOR_MODEL_ID,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You draft safe multi-step Telegram action plans for a personal assistant.\n"
                        "Return ONLY valid JSON.\n"
                        "If one normal reply is enough, return {\"should_propose\": false, \"steps\": []}.\n"
                        "Use a plan only when the incoming message likely needs coordination, "
                        "a follow-up, a reminder, or contacting another known person.\n"
                        "Allowed step types:\n"
                        "- reply_to_sender: fields text, reason\n"
                        "- send_message_to_contact: fields target_ref, text, reason; target_ref MUST be from the allowlist\n"
                        "- create_reminder: fields message_text, reminder_datetime_iso, reason; ISO must include timezone when possible\n"
                        "- ask_user_clarification: fields question, reason\n"
                        "Never invent contact refs. Never include more than "
                        f"{app_settings.USERBOT_ACTION_PLAN_MAX_STEPS} steps."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "<context>\n"
                        + "\n\n".join(context_parts)
                        + "\n</context>\n\n"
                        f"<new_message>\n{sender_name}: {message_text[:800]}\n</new_message>"
                    ),
                },
            ],
            max_tokens=700,
            temperature=0.2,
        )
        raw = (response.choices[0].message.content or "").strip()
        parsed = _parse_json_object(raw)
        return _sanitize_action_plan(parsed, target_candidates)
    except Exception as exc:
        logger.debug("Userbot action plan generation failed for user {}: {}", user_id, exc)
        return None


def _parse_json_object(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("Action plan JSON root must be an object")
    return value


def _sanitize_action_plan(raw_plan: dict, target_candidates: list[dict]) -> dict | None:
    if not raw_plan.get("should_propose"):
        return None

    candidate_by_ref = {
        str(candidate.get("ref")): candidate for candidate in target_candidates if candidate.get("ref")
    }
    steps: list[dict] = []
    raw_steps = raw_plan.get("steps")
    if not isinstance(raw_steps, list):
        return None

    for raw_step in raw_steps[: app_settings.USERBOT_ACTION_PLAN_MAX_STEPS]:
        if not isinstance(raw_step, dict):
            continue
        step = _sanitize_action_step(raw_step, candidate_by_ref)
        if step:
            steps.append(step)

    if not steps:
        return None

    return {
        "title": _short_summary(str(raw_plan.get("title") or "Suggested action plan"), 80),
        "steps": steps,
    }


def _sanitize_action_step(raw_step: dict, candidate_by_ref: dict[str, dict]) -> dict | None:
    step_type = str(raw_step.get("type") or "").strip()
    reason = _short_summary(str(raw_step.get("reason") or ""), 160)

    if step_type == "reply_to_sender":
        text = _short_summary(str(raw_step.get("text") or ""), 900)
        if not text:
            return None
        return {
            "type": "reply_to_sender",
            "text": text,
            "reason": reason,
            "status": "pending",
            "requires_separate_approval": False,
        }

    if step_type == "send_message_to_contact":
        text = _short_summary(str(raw_step.get("text") or ""), 900)
        target_ref = str(raw_step.get("target_ref") or "").strip()
        target = candidate_by_ref.get(target_ref)
        if not text:
            return None
        if not target:
            target_name = _short_summary(str(raw_step.get("target_name") or target_ref or "contact"), 80)
            return {
                "type": "ask_user_clarification",
                "question": f"Which Telegram chat should receive this draft for {target_name}?",
                "draft_text": text,
                "reason": reason,
                "status": "pending",
                "requires_separate_approval": False,
            }
        return {
            "type": "send_message_to_contact",
            "target_ref": target_ref,
            "target_chat_id": target["chat_id"],
            "target_label": target["label"],
            "text": text,
            "reason": reason,
            "status": "pending",
            "requires_separate_approval": True,
        }

    if step_type == "create_reminder":
        message_text = _short_summary(str(raw_step.get("message_text") or ""), 500)
        reminder_datetime_iso = _short_summary(
            str(raw_step.get("reminder_datetime_iso") or ""), 80
        )
        if not message_text:
            return None
        return {
            "type": "create_reminder",
            "message_text": message_text,
            "reminder_datetime_iso": reminder_datetime_iso,
            "reason": reason,
            "status": "pending",
            "requires_separate_approval": False,
        }

    if step_type == "ask_user_clarification":
        question = _short_summary(str(raw_step.get("question") or ""), 400)
        if not question:
            return None
        return {
            "type": "ask_user_clarification",
            "question": question,
            "reason": reason,
            "status": "pending",
            "requires_separate_approval": False,
        }

    return None


def _format_action_plan_for_notification(action_plan: dict) -> str:
    steps = action_plan.get("steps") or []
    if not steps:
        return ""

    lines = ["\n🧭 <b>Suggested action plan:</b>"]
    for index, step in enumerate(steps, 1):
        lines.append(f"{index}. {_esc(_describe_action_step(step))}")
    return "\n".join(lines) + "\n"


def _describe_action_step(step: dict) -> str:
    step_type = step.get("type")
    if step_type == "reply_to_sender":
        return f"Reply here: {step.get('text', '')}"
    if step_type == "send_message_to_contact":
        return f"Message {step.get('target_label', 'contact')}: {step.get('text', '')}"
    if step_type == "create_reminder":
        when = step.get("reminder_datetime_iso") or "time not set"
        return f"Create reminder ({when}): {step.get('message_text', '')}"
    if step_type == "ask_user_clarification":
        draft = step.get("draft_text")
        suffix = f" Draft: {draft}" if draft else ""
        return f"Ask you: {step.get('question', '')}{suffix}"
    return "Review suggested action"


def _action_step_is_executable(step: dict) -> bool:
    if step.get("type") in {"reply_to_sender", "send_message_to_contact"}:
        return bool(step.get("text"))
    if step.get("type") == "create_reminder":
        return bool(step.get("message_text") and step.get("reminder_datetime_iso"))
    return False


def _action_step_is_editable(step: dict) -> bool:
    return step.get("type") in {"reply_to_sender", "send_message_to_contact"}


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
        summaries = "; ".join(
            f"{it['channel_name']}: {it['summary']}" for it in items
        )
        await _save_notification_to_history(
            tg_chat_id=tg_id,
            text=f"[Channel digest — {len(items)} posts]: {summaries}",
        )
        logger.info(
            "Userbot: flushed channel digest ({} posts) for user {}",
            len(items), user_id,
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


async def _generate_reply_suggestions(
    *,
    user_id: int,
    message_text: str,
    sender_name: str,
    sender_tg_id: int,
    conversation_thread: list[dict],
    user_facts: list[str],
    style_samples: list[str],
    sender_relationship: str | None,
) -> list[str]:
    """
    Generate 3 reply suggestions that sound like the user themselves would write.

    Uses rich context: user profile, communication style samples,
    conversation history, and sender relationship.
    """
    _fallback = ["Got it, thanks!", "Sure, I'll get back to you.", "Sounds good!"]
    try:
        # --- Build the system prompt ---
        system_parts = [
            "You are ghostwriting replies for a real person. "
            "Your goal is to write EXACTLY as this person would — "
            "same language, tone, formality, emoji usage, message length, and style."
        ]

        # User profile
        if user_facts:
            facts_block = "\n".join(f"- {f}" for f in user_facts[:20])
            system_parts.append(
                f"\n<user_profile>\n{facts_block}\n</user_profile>"
            )

        # Communication style samples (few-shot examples of how the user writes)
        if style_samples:
            # Show most recent 15 samples
            samples_block = "\n".join(
                f"- \"{s}\"" for s in style_samples[:15]
            )
            system_parts.append(
                "\n<communication_style>\n"
                "Here are real messages this person recently sent. "
                "Mimic their language, length, tone, and quirks:\n"
                f"{samples_block}\n"
                "</communication_style>"
            )

        # Sender relationship
        if sender_relationship:
            system_parts.append(
                f"\n<sender_relationship>\n"
                f"{sender_name}: {sender_relationship}\n"
                f"</sender_relationship>"
            )

        system_parts.append(
            "\nGenerate exactly 3 reply options.\n"
            "Each reply should sound natural and authentic to this person.\n"
            "Output one reply per line, no numbering, no quotes, no extra text.\n"
            "Match the language of the conversation."
        )

        system_prompt = "\n".join(system_parts)

        # --- Build the user prompt with conversation thread ---
        user_parts = []

        if conversation_thread:
            thread_lines = []
            for msg in conversation_thread:
                role_label = "ME" if msg["is_me"] else msg["name"]
                thread_lines.append(f"[{role_label}]: {msg['text']}")
            thread_block = "\n".join(thread_lines)
            user_parts.append(
                f"<conversation_history>\n{thread_block}\n</conversation_history>\n"
            )

        user_parts.append(
            f"<new_message>\n"
            f"[{sender_name}]: {message_text[:500]}\n"
            f"</new_message>\n\n"
            f"Write 3 reply options as ME:"
        )

        user_prompt = "\n".join(user_parts)

        response = await async_client.chat.completions.create(
            model=app_settings.EXTRACTOR_MODEL_ID,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=300,
            temperature=0.7,
        )
        raw = (response.choices[0].message.content or "").strip()
        lines = [line.strip().strip('"').strip("'") for line in raw.splitlines() if line.strip()]
        # Remove any numbering like "1. " or "1) "
        cleaned = []
        for line in lines:
            cleaned_line = re.sub(r"^\d+[\.\)]\s*", "", line).strip()
            if cleaned_line:
                cleaned.append(cleaned_line)
        suggestions = cleaned[:3] if cleaned else _fallback

        # --- Infer sender relationship in background if not cached ---
        if not sender_relationship and conversation_thread:
            asyncio.create_task(
                _infer_and_cache_sender_relationship(
                    user_id=user_id,
                    sender_tg_id=sender_tg_id,
                    sender_name=sender_name,
                    conversation_thread=conversation_thread,
                )
            )

        return suggestions

    except Exception as exc:
        logger.warning("Userbot reply suggestion LLM error: {}", exc)
        return _fallback


async def _infer_and_cache_sender_relationship(
    *,
    user_id: int,
    sender_tg_id: int,
    sender_name: str,
    conversation_thread: list[dict],
) -> None:
    """
    Ask the LLM to infer the relationship between the user and sender
    based on conversation context. Cache the result in Redis.
    """
    try:
        # Build a short conversation summary for the LLM
        thread_lines = []
        for msg in conversation_thread[-6:]:
            role = "User" if msg["is_me"] else msg["name"]
            thread_lines.append(f"{role}: {msg['text'][:150]}")
        thread_text = "\n".join(thread_lines)

        response = await async_client.chat.completions.create(
            model=app_settings.EXTRACTOR_MODEL_ID,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Based on the conversation below, describe the relationship "
                        "between the user and the other person in 5-10 words. "
                        "Examples: 'close friend, informal tone', 'work colleague', "
                        "'boss/manager, formal', 'family member', 'acquaintance'. "
                        "Reply with ONLY the relationship description, nothing else."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Conversation between the user and {sender_name}:\n"
                        f"{thread_text}\n\n"
                        f"Relationship:"
                    ),
                },
            ],
            max_tokens=30,
            temperature=0,
        )
        description = (response.choices[0].message.content or "").strip()
        if description and len(description) < 100:
            await _update_sender_relationship(user_id, sender_tg_id, description)
            logger.info(
                "Userbot: inferred relationship for user {} ↔ {}: {}",
                user_id, sender_name, description,
            )
    except Exception as exc:
        logger.debug("Sender relationship inference failed: {}", exc)


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


async def _get_tg_chat_id(user_id: int) -> int | None:
    """Look up the Telegram chat_id (tg_chat_id) for sending bot notifications."""
    chat_id, _ = await _get_tg_delivery(user_id)
    return chat_id


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
        logger.error("Userbot: could not fetch tg_chat_id for user {}: {}", user_id, exc)
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
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
