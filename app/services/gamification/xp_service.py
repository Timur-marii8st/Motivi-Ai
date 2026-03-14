"""XP & Leveling Engine.

Handles XP awards, daily caps (anti-abuse via Redis), level calculation,
and emits XP_EARNED / LEVEL_UP domain events through the event bus.
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
from app.services.event_bus import event_bus
from app.services.gamification.schemas import (
    EVENT_TO_SKILL,
    GameEvent,
    GameEventType,
    LEVEL_THRESHOLDS,
    SkillCategory,
    UserLevel,
    XP_AMOUNTS,
    XP_DAILY_CAPS,
    XPAction,
)

_redis: aioredis.Redis | None = None


async def _get_redis() -> aioredis.Redis:
    """Lazy-initialise a module-level Redis connection."""
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


# ── Pure helpers ─────────────────────────────────────────────────


def get_level_for_xp(total_xp: int) -> UserLevel:
    """Return the level corresponding to *total_xp*.

    Iterates thresholds in descending order and returns the first level
    whose threshold is <= total_xp.
    """
    for level in reversed(list(UserLevel)):
        if total_xp >= LEVEL_THRESHOLDS[level]:
            return level
    return UserLevel.BEGINNER


def get_xp_to_next_level(total_xp: int) -> tuple[UserLevel, int]:
    """Return (next_level, xp_remaining_to_reach_it).

    If the user is already at the maximum level, returns (current_level, 0).
    """
    current = get_level_for_xp(total_xp)
    levels = list(UserLevel)
    idx = levels.index(current)
    if idx >= len(levels) - 1:
        # Already at max level
        return current, 0
    next_level = levels[idx + 1]
    remaining = LEVEL_THRESHOLDS[next_level] - total_xp
    return next_level, max(remaining, 0)


# ── Core service functions ───────────────────────────────────────


async def award_xp(
    session: AsyncSession,
    user_id: int,
    action: XPAction,
    amount_override: int | None = None,
) -> tuple[int, str | None]:
    """Award XP for *action*, respecting daily caps.

    Returns ``(xp_actually_awarded, new_level_name_or_None)``.
    If the feature flag is off or the daily cap is exhausted, returns ``(0, None)``.
    """
    if not settings.is_feature_enabled("F001_XP_ENGINE"):
        return 0, None

    amount = amount_override if amount_override is not None else XP_AMOUNTS.get(action, 0)
    if amount <= 0:
        return 0, None

    # ── Anti-abuse: Redis daily cap ────────────────────────────
    r = await _get_redis()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cap_key = f"xp_cap:{user_id}:{action.value}:{today}"
    daily_cap = XP_DAILY_CAPS.get(action, 0)

    current_total = await r.get(cap_key)
    current_total = int(current_total) if current_total else 0

    if current_total >= daily_cap:
        logger.debug(
            "XP daily cap reached for user {} action {} ({}/{})",
            user_id, action.value, current_total, daily_cap,
        )
        return 0, None

    # Clamp to remaining allowance
    headroom = daily_cap - current_total
    actual_award = min(amount, headroom)

    pipe = r.pipeline()
    pipe.incrby(cap_key, actual_award)
    pipe.expire(cap_key, 86400 + 3600)
    await pipe.execute()

    # ── Persist XP ─────────────────────────────────────────────
    result = await session.execute(
        select(UserXP).where(UserXP.user_id == user_id)
    )
    user_xp = result.scalar_one_or_none()
    if user_xp is None:
        user_xp = UserXP(user_id=user_id, total_xp=0, level=UserLevel.BEGINNER.value)
        session.add(user_xp)
        await session.flush()

    old_level = get_level_for_xp(user_xp.total_xp)
    user_xp.total_xp += actual_award
    new_level = get_level_for_xp(user_xp.total_xp)
    user_xp.level = new_level.value
    user_xp.touch()
    await session.flush()

    logger.info(
        "Awarded {} XP to user {} for {} (total: {})",
        actual_award, user_id, action.value, user_xp.total_xp,
    )

    # ── Emit XP_EARNED event ───────────────────────────────────
    now = datetime.now(timezone.utc)
    await event_bus.emit(GameEvent(
        event=GameEventType.XP_EARNED,
        user_id=user_id,
        feature_id="F001",
        properties={"action": action.value, "xp": actual_award, "total_xp": user_xp.total_xp},
        timestamp=now,
    ))

    # ── Level-up detection ─────────────────────────────────────
    new_level_name: str | None = None
    if new_level != old_level:
        new_level_name = new_level.value
        logger.info(
            "User {} leveled up: {} -> {}",
            user_id, old_level.value, new_level_name,
        )
        await event_bus.emit(GameEvent(
            event=GameEventType.LEVEL_UP,
            user_id=user_id,
            feature_id="F001",
            properties={
                "old_level": old_level.value,
                "new_level": new_level_name,
                "total_xp": user_xp.total_xp,
            },
            timestamp=now,
        ))

    return actual_award, new_level_name


async def get_user_xp(session: AsyncSession, user_id: int) -> UserXP:
    """Return the UserXP row for *user_id*, creating a default if absent."""
    result = await session.execute(
        select(UserXP).where(UserXP.user_id == user_id)
    )
    user_xp = result.scalar_one_or_none()
    if user_xp is None:
        user_xp = UserXP(user_id=user_id, total_xp=0, level=UserLevel.BEGINNER.value)
        session.add(user_xp)
        await session.flush()
    return user_xp


# ── Event-bus listeners ──────────────────────────────────────────

_ACTION_MAP: dict[GameEventType, XPAction] = {
    GameEventType.HABIT_LOGGED: XPAction.HABIT_LOGGED,
    GameEventType.PLAN_CREATED: XPAction.PLAN_CREATED,
    GameEventType.CODE_EXECUTED: XPAction.CODE_EXECUTED,
    GameEventType.WEB_SEARCHED: XPAction.WEB_SEARCHED,
    GameEventType.CHALLENGE_COMPLETED: XPAction.CHALLENGE_COMPLETED,
    GameEventType.FEATURE_FIRST_USE: XPAction.FEATURE_FIRST_USE,
}


async def _on_xp_triggering_event(event: GameEvent) -> None:
    """Generic listener: map domain event to XPAction and award XP."""
    xp_action = _ACTION_MAP.get(event.event)
    if xp_action is None:
        return
    try:
        async with AsyncSessionLocal() as session:
            await award_xp(session, event.user_id, xp_action)
            await session.commit()
    except Exception:
        logger.exception("Failed to award XP for event {} user {}", event.event.value, event.user_id)


async def _on_message_sent(event: GameEvent) -> None:
    """Award daily-login XP on first message of the day."""
    try:
        async with AsyncSessionLocal() as session:
            await award_xp(session, event.user_id, XPAction.DAILY_LOGIN)
            await session.commit()
    except Exception:
        logger.exception("Failed to award daily login XP for user {}", event.user_id)


# Register listeners
for _evt in (
    GameEventType.HABIT_LOGGED,
    GameEventType.PLAN_CREATED,
    GameEventType.CODE_EXECUTED,
    GameEventType.WEB_SEARCHED,
    GameEventType.CHALLENGE_COMPLETED,
    GameEventType.FEATURE_FIRST_USE,
):
    event_bus.subscribe(_evt, _on_xp_triggering_event)

event_bus.subscribe(GameEventType.MESSAGE_SENT, _on_message_sent)
