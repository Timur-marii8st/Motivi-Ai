"""Gamification commands router.

/level — show current XP and level
/badges — show badge collection
/leaderboard — show rankings
"""
from __future__ import annotations

from aiogram import Router, F
from aiogram.types import Message
from loguru import logger

from ...config import settings
from ...services.profile_services import get_or_create_user

router = Router(name="gamification")


@router.message(F.text == "/level")
async def level_cmd(message: Message, session):
    """Show user's current XP, level, and progress to next level."""
    if not settings.is_feature_enabled("F001_XP_ENGINE"):
        await message.answer("Gamification features are not yet enabled.")
        return

    user = await get_or_create_user(session, message.from_user.id, message.chat.id)

    from ...services.gamification.xp_service import get_user_xp, get_xp_to_next_level

    user_xp = await get_user_xp(session, user.id)
    next_level, remaining = get_xp_to_next_level(user_xp.total_xp)

    # Build progress bar
    if remaining > 0:
        from ...services.gamification.schemas import LEVEL_THRESHOLDS, UserLevel

        current_threshold = LEVEL_THRESHOLDS.get(
            UserLevel(user_xp.level), 0
        )
        next_threshold = LEVEL_THRESHOLDS.get(next_level, user_xp.total_xp)
        range_xp = next_threshold - current_threshold
        progress = user_xp.total_xp - current_threshold
        pct = min(progress / max(range_xp, 1), 1.0)
        filled = int(pct * 10)
        bar = "█" * filled + "░" * (10 - filled)
        progress_text = (
            f"[{bar}] {progress}/{range_xp} XP to {next_level.value}"
        )
    else:
        progress_text = "🏆 Maximum level reached!"

    # Streak info
    from ...services.streak_service import StreakService

    streak_text = StreakService.get_streak_display(user)

    await message.answer(
        f"⭐ <b>Level: {user_xp.level}</b>\n"
        f"💎 Total XP: <b>{user_xp.total_xp}</b>\n"
        f"{progress_text}\n"
        f"{streak_text}"
    )


@router.message(F.text == "/badges")
async def badges_cmd(message: Message, session):
    """Show user's badge collection with progress."""
    if not settings.is_feature_enabled("F003_BADGES"):
        await message.answer("Badge system is not yet enabled.")
        return

    user = await get_or_create_user(session, message.from_user.id, message.chat.id)

    from ...services.gamification.badge_service import get_user_badges

    badges = await get_user_badges(session, user.id)

    if not badges:
        await message.answer("🏅 No badges available yet!")
        return

    lines = ["🏅 <b>Your Badges</b>\n"]

    unlocked = [b for b in badges if b["unlocked"]]
    locked = [b for b in badges if not b["unlocked"]]

    if unlocked:
        lines.append("<b>Unlocked:</b>")
        for b in unlocked:
            lines.append(f"  {b['icon']} <b>{b['name']}</b> — {b['description']}")

    if locked:
        lines.append("\n<b>In Progress:</b>")
        for b in locked:
            lines.append(
                f"  {b['icon']} {b['name']} — {b['progress']}/{b['target']}"
            )

    await message.answer("\n".join(lines))


@router.message(F.text.startswith("/leaderboard"))
async def leaderboard_cmd(message: Message, session):
    """Show the leaderboard."""
    if not settings.is_feature_enabled("F005_LEADERBOARD"):
        await message.answer("Leaderboard is not yet enabled.")
        return

    user = await get_or_create_user(session, message.from_user.id, message.chat.id)

    # Parse optional window argument
    parts = message.text.strip().split()
    window = "weekly"
    if len(parts) > 1 and parts[1] in ("alltime", "weekly", "monthly"):
        window = parts[1]

    from ...services.gamification.leaderboard_service import (
        format_leaderboard_message,
    )

    text = await format_leaderboard_message(session, user.id, window)
    await message.answer(text)
