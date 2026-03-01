"""
UserBotMonitor — Telethon event handlers and LLM-powered notification logic.

Two types of events are handled:
  1. New posts in channels the user is subscribed to.
     → An LLM classifies whether the post is relevant to the user's interests.
       If yes, a formatted notification is sent via the bot.
  2. Incoming private messages (DMs) to the user's personal account.
     → The LLM suggests 3 short reply options.
       A formatted notification with the suggestions is sent via the bot.

Safety guarantees
-----------------
* Read-only: handlers never call any Telethon write API.
  No send_message, mark_as_read, react, or similar methods are used.
* Telethon's NewMessage event does NOT mark messages as read automatically.
* Rate limiting via Redis prevents channel-notification floods.
"""
from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

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


# ---------------------------------------------------------------------------
# Channel post handler
# ---------------------------------------------------------------------------

async def _handle_channel_post(event, user_id: int, bot: "Bot") -> None:
    try:
        # Skip if user disabled channel monitoring
        user_settings = await _get_user_settings(user_id)
        if user_settings and not user_settings.enable_channel_monitoring:
            return

        text: str = event.message.message or ""
        if len(text) < 30:
            return  # too short to be meaningful news

        # Rate-limit: max N notifications per user × channel × day
        channel_id = event.chat_id
        today_str = date.today().isoformat()
        rate_key = f"userbot_notif:{user_id}:{channel_id}:{today_str}"

        redis = await _get_redis()
        try:
            count = await redis.incr(rate_key)
            if count == 1:
                await redis.expire(rate_key, 90_000)  # 25-hour TTL
            if count > app_settings.USERBOT_MAX_CHANNEL_NOTIFS_PER_DAY:
                return
        finally:
            await redis.aclose()

        # LLM relevance filter
        interests = await _get_channel_interests(user_id)
        if not await _is_content_interesting(text, interests):
            return

        # Fetch channel metadata (username for deep-link)
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
# DM handler
# ---------------------------------------------------------------------------

async def _handle_dm(event, user_id: int, bot: "Bot") -> None:
    try:
        # Skip if user disabled DM notifications
        user_settings = await _get_user_settings(user_id)
        if user_settings and not user_settings.enable_dm_notifications:
            return

        text: str = event.message.message or ""
        if not text.strip():
            return  # media-only message — nothing to suggest replies for

        # Sender info
        sender = await event.get_sender()
        first = getattr(sender, "first_name", None) or ""
        last = getattr(sender, "last_name", None) or ""
        sender_name = (f"{first} {last}".strip() or getattr(sender, "username", None) or "Someone")

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

        tg_id = await _get_tg_user_id(user_id)
        if tg_id:
            await bot.send_message(tg_id, notification, parse_mode="HTML")
            logger.info(
                "Userbot: sent DM notification to user {} from {}", user_id, sender_name
            )
    except Exception as exc:
        logger.error("Userbot DM handler error (user {}): {}", user_id, exc)


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
        return False  # don't notify on error


async def _generate_reply_suggestions(message_text: str, sender_name: str) -> list[str]:
    """Return up to 3 short reply suggestions for an incoming DM."""
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
                        "Output one reply per line, no numbering, no extra text."
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
