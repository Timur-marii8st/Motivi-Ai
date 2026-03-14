"""Leaderboard Engine.

Uses Redis sorted sets for O(log N) ranking queries.
Supports all-time, monthly, and weekly windows.
Users can opt out via UserSettings.show_on_leaderboard.
"""
from __future__ import annotations

from datetime import datetime, timezone

import redis.asyncio as aioredis
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.config import settings
from app.db import AsyncSessionLocal
from app.models.gamification import UserXP
from app.models.settings import UserSettings
from app.models.users import User
from app.services.event_bus import event_bus
from app.services.gamification.schemas import GameEvent, GameEventType

_redis: aioredis.Redis | None = None

_KEY_ALL_TIME = "leaderboard:alltime"


async def _get_redis() -> aioredis.Redis:
    """Lazy Redis connection."""
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


def _weekly_key() -> str:
    """Redis key for the current ISO week."""
    now = datetime.now(timezone.utc)
    year, week, _ = now.isocalendar()
    return f"leaderboard:weekly:{year}:W{week:02d}"


def _monthly_key() -> str:
    """Redis key for the current month."""
    now = datetime.now(timezone.utc)
    return f"leaderboard:monthly:{now.strftime('%Y-%m')}"


async def update_score(user_id: int, xp_earned: int) -> None:
    """Increment user's leaderboard scores across all time windows."""
    if not settings.is_feature_enabled("F005_LEADERBOARD"):
        return
    try:
        r = await _get_redis()
        pipe = r.pipeline()
        member = str(user_id)
        pipe.zincrby(_KEY_ALL_TIME, xp_earned, member)
        pipe.zincrby(_weekly_key(), xp_earned, member)
        pipe.zincrby(_monthly_key(), xp_earned, member)
        # Weekly keys expire after 8 days, monthly after 32 days
        pipe.expire(_weekly_key(), 8 * 86400)
        pipe.expire(_monthly_key(), 32 * 86400)
        await pipe.execute()
    except Exception:
        logger.exception("Failed to update leaderboard for user {}", user_id)


async def get_leaderboard(
    window: str = "alltime",
    top_n: int = 10,
) -> list[dict]:
    """Fetch the top N entries from a leaderboard window.

    *window*: "alltime" | "weekly" | "monthly"
    Returns list of {"user_id": int, "score": float, "rank": int}.
    """
    if not settings.is_feature_enabled("F005_LEADERBOARD"):
        return []

    key_map = {
        "alltime": _KEY_ALL_TIME,
        "weekly": _weekly_key(),
        "monthly": _monthly_key(),
    }
    key = key_map.get(window, _KEY_ALL_TIME)

    try:
        r = await _get_redis()
        entries = await r.zrevrange(key, 0, top_n - 1, withscores=True)
        result = []
        for rank, (member, score) in enumerate(entries, 1):
            result.append(
                {"user_id": int(member), "score": int(score), "rank": rank}
            )
        return result
    except Exception:
        logger.exception("Failed to fetch leaderboard (window={})", window)
        return []


async def get_user_rank(
    user_id: int,
    window: str = "alltime",
) -> dict | None:
    """Get a specific user's rank and score."""
    if not settings.is_feature_enabled("F005_LEADERBOARD"):
        return None

    key_map = {
        "alltime": _KEY_ALL_TIME,
        "weekly": _weekly_key(),
        "monthly": _monthly_key(),
    }
    key = key_map.get(window, _KEY_ALL_TIME)

    try:
        r = await _get_redis()
        rank = await r.zrevrank(key, str(user_id))
        if rank is None:
            return None
        score = await r.zscore(key, str(user_id))
        return {
            "user_id": user_id,
            "rank": rank + 1,
            "score": int(score) if score else 0,
        }
    except Exception:
        logger.exception(
            "Failed to get rank for user {} (window={})", user_id, window
        )
        return None


async def format_leaderboard_message(
    session: AsyncSession,
    user_id: int,
    window: str = "weekly",
) -> str:
    """Build a formatted leaderboard message for Telegram."""
    entries = await get_leaderboard(window, top_n=10)
    if not entries:
        return "🏆 Leaderboard is empty. Be the first!"

    window_labels = {
        "alltime": "All-Time",
        "weekly": "This Week",
        "monthly": "This Month",
    }
    label = window_labels.get(window, "All-Time")

    # Check opt-out settings for visible users
    lines = [f"🏆 <b>Leaderboard — {label}</b>\n"]
    for entry in entries:
        uid = entry["user_id"]
        # Check if user opted out
        us_result = await session.execute(
            select(UserSettings.show_on_leaderboard).where(
                UserSettings.user_id == uid
            )
        )
        show = us_result.scalar_one_or_none()
        if show is False:
            continue

        user = await session.get(User, uid)
        name = user.name if user and user.name else f"User #{uid}"
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(entry["rank"], "  ")
        lines.append(
            f"{medal} #{entry['rank']} {name} — {entry['score']} XP"
        )

    # Append user's own rank
    my_rank = await get_user_rank(user_id, window)
    if my_rank and my_rank["rank"] > 10:
        lines.append(f"\n📍 Your rank: #{my_rank['rank']} ({my_rank['score']} XP)")

    return "\n".join(lines)


# ── Event bus listener ────────────────────────────────────────────
async def _on_xp_earned(event: GameEvent) -> None:
    """Update leaderboard when XP is earned."""
    xp = event.properties.get("xp", 0)
    if xp > 0:
        await update_score(event.user_id, xp)


event_bus.subscribe(GameEventType.XP_EARNED, _on_xp_earned)
