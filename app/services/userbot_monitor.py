"""
UserBotMonitor — Telethon event handlers and LLM-powered notification logic.

Three types of events are handled:
  1. New posts in channels the user is subscribed to.
     → An LLM classifies whether the post is relevant to the user's interests.
       If yes, a formatted notification is sent via the bot.
  2. Incoming private messages (DMs) to the user's personal account.
     → The LLM suggests 3 short reply options.
       A formatted notification with approval buttons is sent via the bot.
  3. Incoming group/supergroup messages mentioning the user or replying to them.
     → Same as DMs: LLM suggests replies with approval buttons.

Safety guarantees
-----------------
* Telethon write operations (send_message, send_chat_action) are ONLY called
  after explicit user approval via bot callback buttons (human-in-the-loop).
* Human-like delays and typing simulation are applied before sending.
* Rate limiting via Redis prevents notification and reply floods.
* All pending replies expire after USERBOT_REPLY_TIMEOUT seconds.
"""
from __future__ import annotations

import json
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
        await _handle_dm(event, user_id, bot)

    @client.on(events.NewMessage(incoming=True, func=lambda e: e.is_group))
    async def on_group(event):
        await _handle_group_message(event, user_id, bot, client)


# ---------------------------------------------------------------------------
# Channel post handler (unchanged logic)
# ---------------------------------------------------------------------------

async def _handle_channel_post(event, user_id: int, bot: "Bot") -> None:
    try:
        user_settings = await _get_user_settings(user_id)
        if user_settings and not user_settings.enable_channel_monitoring:
            return

        text: str = event.message.message or ""
        if len(text) < 30:
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

        interests = await _get_channel_interests(user_id)
        if not await _is_content_interesting(text, interests):
            return

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

        tg_id = await _get_tg_user_id(user_id)
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
# DM handler — with approval buttons
# ---------------------------------------------------------------------------

async def _handle_dm(event, user_id: int, bot: "Bot") -> None:
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

        suggestions = await _generate_reply_suggestions(text, sender_name)

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

        tg_id = await _get_tg_user_id(user_id)
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

        suggestions = await _generate_reply_suggestions(text, sender_name)

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

        tg_id = await _get_tg_user_id(user_id)
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
    import hashlib
    import time

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
    """Return True if the user is under their daily reply limit."""
    today_str = date.today().isoformat()
    rate_key = f"ub_replies:{user_id}:{today_str}"

    redis = await _get_redis()
    try:
        async with redis.pipeline(transaction=True) as pipe:
            pipe.incr(rate_key)
            pipe.execute_command("EXPIRE", rate_key, 90_000, "NX")
            pipe_result = await pipe.execute()
        count = int(pipe_result[0])
        if count > app_settings.USERBOT_MAX_REPLIES_PER_DAY:
            return False
        return True
    finally:
        await redis.aclose()


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------

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


async def _generate_reply_suggestions(message_text: str, sender_name: str) -> list[str]:
    """Return up to 3 short reply suggestions for an incoming message."""
    _fallback = ["Got it, thanks!", "Sure, I'll get back to you.", "Sounds good!"]
    try:
        response = await async_client.chat.completions.create(
            model=app_settings.EXTRACTOR_MODEL_ID,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a personal assistant helping draft concise, natural replies. "
                        "Generate exactly 3 short reply options (1 sentence each). "
                        "Output one reply per line, no numbering, no extra text. "
                        "Match the language of the original message."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f'{sender_name} sent: "{message_text[:500]}"\n\n'
                        "Write 3 reply options:"
                    ),
                },
            ],
            max_tokens=200,
            temperature=0.7,
        )
        raw = (response.choices[0].message.content or "").strip()
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        return lines[:3] if lines else _fallback
    except Exception as exc:
        logger.warning("Userbot reply suggestion LLM error: {}", exc)
        return _fallback


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


async def _get_tg_user_id(user_id: int) -> int | None:
    """Look up the Telegram user_id (tg_user_id) for a bot-user row."""
    try:
        from ..db import get_session
        from ..models.users import User

        async with get_session() as session:
            user = await session.get(User, user_id)
            return user.tg_user_id if user else None
    except Exception as exc:
        logger.error("Userbot: could not fetch tg_user_id for user {}: {}", user_id, exc)
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
