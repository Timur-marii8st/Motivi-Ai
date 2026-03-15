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
from datetime import date
from typing import TYPE_CHECKING

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from loguru import logger
from telethon import TelegramClient, events

from ..config import settings as app_settings
from ..llm.client import async_client

if TYPE_CHECKING:
    from aiogram import Bot


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------

def setup_handlers(client: TelegramClient, user_id: int, bot: "Bot") -> None:
    """Register all Telethon event handlers for *one* user's client."""

    @client.on(events.NewMessage(incoming=True, func=lambda e: e.is_channel))
    async def on_channel_post(event):
        await _handle_channel_post(event, user_id, bot)

    @client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
    async def on_dm(event):
        await _handle_dm(event, user_id, bot, client)

    @client.on(events.NewMessage(incoming=True, func=lambda e: e.is_group))
    async def on_group(event):
        await _handle_group_message(event, user_id, bot, client)

    # Learn communication style from the user's own outgoing messages
    @client.on(events.NewMessage(outgoing=True, func=lambda e: e.is_private or e.is_group))
    async def on_outgoing(event):
        await _handle_outgoing_message(event, user_id)


# ---------------------------------------------------------------------------
# Channel post handler
# ---------------------------------------------------------------------------

async def _handle_channel_post(event, user_id: int, bot: "Bot") -> None:
    try:
        user_settings = await _get_user_settings(user_id)
        if user_settings and not user_settings.enable_channel_monitoring:
            return

        text: str = event.message.message or ""
        if len(text) < 30:
            return

        # Check interest BEFORE incrementing rate limit counter,
        # so non-interesting posts don't waste the daily quota.
        interests = await _get_channel_interests(user_id)
        if not await _is_content_interesting(text, interests):
            return

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

        chat = await event.get_chat()
        channel_name = (
            getattr(chat, "title", None)
            or getattr(chat, "username", None)
            or f"channel {channel_id}"
        )
        channel_username = getattr(chat, "username", None)

        excerpt = text[:600].strip()
        if len(text) > 600:
            excerpt += "…"

        post_link = ""
        if channel_username and event.message.id:
            post_link = (
                f"\n🔗 <a href='https://t.me/{channel_username}/{event.message.id}'>"
                f"Open post</a>"
            )

        notification = (
            f"📰 <b>Interesting from {_esc(channel_name)}:</b>\n"
            f"━━━━━━━━━━━━\n"
            f"{_esc(excerpt)}"
            f"{post_link}"
        )

        tg_id = await _get_tg_chat_id(user_id)
        if tg_id:
            await bot.send_message(
                tg_id, notification, parse_mode="HTML", disable_web_page_preview=True
            )
            logger.info(
                "Userbot: sent channel notification to user {} from {}", user_id, channel_name
            )
    except Exception as exc:
        logger.error("Userbot channel handler error (user {}): {}", user_id, exc)


# ---------------------------------------------------------------------------
# Outgoing message handler — style learning
# ---------------------------------------------------------------------------

async def _handle_outgoing_message(event, user_id: int) -> None:
    """
    Collect the user's own outgoing messages as communication style samples.
    Stored in a Redis ring buffer (LPUSH + LTRIM).
    Bot-sent replies are filtered out via a short-lived skip marker.
    """
    try:
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

    except Exception as exc:
        logger.debug("Userbot outgoing handler error (user {}): {}", user_id, exc)


# ---------------------------------------------------------------------------
# DM handler — with approval buttons
# ---------------------------------------------------------------------------

async def _handle_dm(event, user_id: int, bot: "Bot", client: TelegramClient) -> None:
    try:
        user_settings = await _get_user_settings(user_id)
        if user_settings and not user_settings.enable_dm_notifications:
            return

        text: str = event.message.message or ""
        if not text.strip():
            return

        sender = await event.get_sender()
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

        # Determine if we show approval buttons
        show_buttons = user_settings and user_settings.enable_reply_approval if user_settings else True

        tg_id = await _get_tg_chat_id(user_id)
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
            )

            keyboard = _build_approval_keyboard(pending_key, len(suggestions))
            await bot.send_message(
                tg_id, notification, parse_mode="HTML", reply_markup=keyboard
            )
        else:
            await bot.send_message(tg_id, notification, parse_mode="HTML")

        logger.info(
            "Userbot: sent DM notification to user {} from {}", user_id, sender_name
        )
    except Exception as exc:
        logger.error("Userbot DM handler error (user {}): {}", user_id, exc)


# ---------------------------------------------------------------------------
# Group message handler — with approval buttons
# ---------------------------------------------------------------------------

async def _handle_group_message(
    event, user_id: int, bot: "Bot", client: TelegramClient
) -> None:
    """
    Handle incoming group/supergroup messages.
    Only react to messages that mention the user or reply to the user's messages.
    """
    try:
        user_settings = await _get_user_settings(user_id)
        if user_settings and not user_settings.enable_group_monitoring:
            return

        text: str = event.message.message or ""
        if not text.strip():
            return

        # Only process messages that are relevant to the user:
        # 1. Direct reply to user's message
        # 2. Message mentions the user
        me = await client.get_me()
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
            if count > app_settings.USERBOT_MAX_CHANNEL_NOTIFS_PER_DAY:
                return
        finally:
            await redis.aclose()

        sender = await event.get_sender()
        first = getattr(sender, "first_name", None) or ""
        last = getattr(sender, "last_name", None) or ""
        sender_name = f"{first} {last}".strip() or getattr(sender, "username", None) or "Someone"
        sender_tg_id = getattr(sender, "id", 0)

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

        tg_id = await _get_tg_chat_id(user_id)
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
            )
            keyboard = _build_approval_keyboard(pending_key, len(suggestions))
            await bot.send_message(
                tg_id, notification, parse_mode="HTML", reply_markup=keyboard
            )
        else:
            await bot.send_message(tg_id, notification, parse_mode="HTML")

        logger.info(
            "Userbot: sent group notification to user {} from {} in {}",
            user_id, sender_name, chat_title,
        )
    except Exception as exc:
        logger.error("Userbot group handler error (user {}): {}", user_id, exc)


# ---------------------------------------------------------------------------
# Approval keyboard builder
# ---------------------------------------------------------------------------

def _build_approval_keyboard(pending_key: str, num_suggestions: int) -> InlineKeyboardMarkup:
    """Build inline keyboard with Send/Edit/Dismiss buttons."""
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
    rows.append(suggestion_buttons)

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
        await redis.delete(f"ub_pending:{pending_key}")
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


# ===========================================================================
# LLM helpers
# ===========================================================================

async def _is_content_interesting(text: str, interests: str) -> bool:
    """YES/NO LLM classification using the lightweight extractor model."""
    try:
        response = await async_client.chat.completions.create(
            model=app_settings.EXTRACTOR_MODEL_ID,
            messages=[
                {
                    "role": "system",
                    "content": "You are a content relevance classifier. Reply ONLY with YES or NO.",
                },
                {
                    "role": "user",
                    "content": (
                        f"User interests: {interests}\n\n"
                        f"Channel post:\n{text[:1000]}\n\n"
                        "Is this post relevant and interesting for this user? YES or NO:"
                    ),
                },
            ],
            max_tokens=5,
            temperature=0,
        )
        answer = (response.choices[0].message.content or "").strip().upper()
        return answer.startswith("YES")
    except Exception as exc:
        logger.warning("Userbot interest check LLM error: {}", exc)
        return False


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
    try:
        from ..db import get_session
        from ..models.users import User

        async with get_session() as session:
            user = await session.get(User, user_id)
            return user.tg_chat_id if user else None
    except Exception as exc:
        logger.error("Userbot: could not fetch tg_chat_id for user {}: {}", user_id, exc)
        return None


async def _get_redis():
    from redis.asyncio import Redis
    return Redis.from_url(app_settings.REDIS_URL)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _esc(text: str) -> str:
    """Escape HTML special characters for Telegram HTML parse mode."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
