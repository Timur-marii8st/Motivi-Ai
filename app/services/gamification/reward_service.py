"""Variable Reward (Mystery Box) System.

Configurable probability tables, pity timer for guaranteed drops,
and full audit logging of all rewards granted.
"""
from __future__ import annotations

import random
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.config import settings
from app.db import AsyncSessionLocal
from app.models.gamification import RewardLog, UserXP
from app.models.users import User
from app.services.event_bus import event_bus
from app.services.gamification.schemas import (
    GameEvent,
    GameEventType,
    PITY_TIMER_THRESHOLD,
    REWARD_PROBABILITIES,
    RewardTier,
    RewardType,
)


# Reward pool per tier
REWARD_POOL: dict[RewardTier, list[dict]] = {
    RewardTier.COMMON: [
        {"type": RewardType.BONUS_XP, "amount": 10, "label": "+10 Bonus XP"},
        {"type": RewardType.BONUS_XP, "amount": 15, "label": "+15 Bonus XP"},
    ],
    RewardTier.RARE: [
        {"type": RewardType.BONUS_XP, "amount": 50, "label": "+50 Bonus XP"},
        {"type": RewardType.STREAK_FREEZE, "amount": 1, "label": "+1 Streak Freeze"},
    ],
    RewardTier.EPIC: [
        {"type": RewardType.BONUS_XP, "amount": 200, "label": "+200 Bonus XP"},
        {"type": RewardType.STREAK_FREEZE, "amount": 2, "label": "+2 Streak Freezes"},
        {"type": RewardType.BADGE_HINT, "amount": 1, "label": "Badge Hint Revealed"},
    ],
}


async def _get_consecutive_commons(session: AsyncSession, user_id: int) -> int:
    """Count consecutive COMMON rewards from the tail of the reward log."""
    result = await session.execute(
        select(RewardLog.reward_tier)
        .where(RewardLog.user_id == user_id)
        .order_by(RewardLog.created_at.desc())
        .limit(PITY_TIMER_THRESHOLD + 1)
    )
    tiers = [row[0] for row in result.all()]
    count = 0
    for t in tiers:
        if t == RewardTier.COMMON.value:
            count += 1
        else:
            break
    return count


def _roll_tier(consecutive_commons: int) -> RewardTier:
    """Roll a reward tier using probability table with pity timer."""
    if consecutive_commons >= PITY_TIMER_THRESHOLD:
        # Guaranteed non-common
        roll = random.random()
        if roll < 0.7:
            return RewardTier.RARE
        return RewardTier.EPIC

    roll = random.random()
    cumulative = 0.0
    for tier, prob in REWARD_PROBABILITIES.items():
        cumulative += prob
        if roll < cumulative:
            return tier
    return RewardTier.COMMON


async def grant_reward(user_id: int) -> dict | None:
    """Roll and grant a variable reward to the user.

    Returns reward info dict or None if feature disabled.
    """
    if not settings.is_feature_enabled("F004_VARIABLE_REWARDS"):
        return None

    session = AsyncSessionLocal()
    try:
        consecutive = await _get_consecutive_commons(session, user_id)
        tier = _roll_tier(consecutive)
        pool = REWARD_POOL.get(tier, REWARD_POOL[RewardTier.COMMON])
        reward = random.choice(pool)

        # Apply reward
        if reward["type"] == RewardType.BONUS_XP:
            xp_result = await session.execute(
                select(UserXP).where(UserXP.user_id == user_id)
            )
            user_xp = xp_result.scalar_one_or_none()
            if user_xp:
                user_xp.total_xp += reward["amount"]
                user_xp.touch()

        elif reward["type"] == RewardType.STREAK_FREEZE:
            user = await session.get(User, user_id)
            if user:
                user.streak_freeze_tokens = min(
                    user.streak_freeze_tokens + reward["amount"], 5
                )
                user.touch()
                session.add(user)

        # Log the reward
        log = RewardLog(
            user_id=user_id,
            reward_type=reward["type"].value,
            reward_tier=tier.value,
            properties_json={
                "label": reward["label"],
                "amount": reward["amount"],
            },
        )
        session.add(log)
        await session.commit()

        logger.info(
            "Granted {} reward ({}) to user {}: {}",
            tier.value,
            reward["type"].value,
            user_id,
            reward["label"],
        )

        await event_bus.emit(
            GameEvent(
                event=GameEventType.REWARD_GRANTED,
                user_id=user_id,
                feature_id="F004",
                properties={
                    "tier": tier.value,
                    "reward_type": reward["type"].value,
                    "label": reward["label"],
                },
                timestamp=datetime.now(timezone.utc),
            )
        )

        return {
            "tier": tier.value,
            "type": reward["type"].value,
            "label": reward["label"],
            "amount": reward["amount"],
        }

    except Exception:
        logger.exception("Failed to grant reward to user {}", user_id)
        await session.rollback()
        return None
    finally:
        await session.close()


# ── Event-bus listener: grant rewards on milestones ──────────────
async def _on_milestone_reward(event: GameEvent) -> None:
    """Grant a mystery reward on streak milestones and level-ups."""
    if not settings.is_feature_enabled("F004_VARIABLE_REWARDS"):
        return
    await grant_reward(event.user_id)


event_bus.subscribe(GameEventType.STREAK_MILESTONE, _on_milestone_reward)
event_bus.subscribe(GameEventType.LEVEL_UP, _on_milestone_reward)
