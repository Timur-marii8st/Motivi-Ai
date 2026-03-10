"""Badge / Achievement Engine.

Badge definitions are data-driven (loaded from BADGE_DEFINITIONS list).
Progress is tracked per (user, badge_id) in the user_badges table.
When a badge unlocks, a celebration message is sent and BADGE_UNLOCKED emitted.
"""
from __future__ import annotations

from datetime import datetime, timezone

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties

from app.config import settings
from app.db import AsyncSessionLocal
from app.models.gamification import UserBadge
from app.models.users import User
from app.services.event_bus import event_bus
from app.services.gamification.schemas import (
    BadgeCategory,
    BadgeDefinition,
    GameEvent,
    GameEventType,
)

# ── Badge Definitions (data-driven) ──────────────────────────────
BADGE_DEFINITIONS: list[BadgeDefinition] = [
    BadgeDefinition(
        badge_id="early_bird",
        name="Early Bird",
        description="Complete a task before 8 AM 5 times",
        category=BadgeCategory.ACTION,
        icon="🌅",
        target_count=5,
        event_type=GameEventType.HABIT_LOGGED,
        event_filter={"hour_before": 8},
    ),
    BadgeDefinition(
        badge_id="streak_legend",
        name="Streak Legend",
        description="Maintain a 30-day conversation streak",
        category=BadgeCategory.MILESTONE,
        icon="🔥",
        target_count=1,
        event_type=GameEventType.STREAK_MILESTONE,
        event_filter={"milestone_gte": 30},
    ),
    BadgeDefinition(
        badge_id="memory_maker",
        name="Memory Maker",
        description="Accumulate 100 memories",
        category=BadgeCategory.MILESTONE,
        icon="🧠",
        target_count=1,
        event_type=GameEventType.MEMORY_MILESTONE,
        event_filter={"milestone_gte": 100},
    ),
    BadgeDefinition(
        badge_id="code_wizard",
        name="Code Wizard",
        description="Execute code 10 times",
        category=BadgeCategory.ACTION,
        icon="🧙",
        target_count=10,
        event_type=GameEventType.CODE_EXECUTED,
    ),
    BadgeDefinition(
        badge_id="planner_pro",
        name="Planner Pro",
        description="Create 10 plans",
        category=BadgeCategory.ACTION,
        icon="📋",
        target_count=10,
        event_type=GameEventType.PLAN_CREATED,
    ),
    BadgeDefinition(
        badge_id="week_warrior",
        name="Week Warrior",
        description="7-day conversation streak",
        category=BadgeCategory.MILESTONE,
        icon="⚔️",
        target_count=1,
        event_type=GameEventType.STREAK_MILESTONE,
        event_filter={"milestone_gte": 7},
    ),
    BadgeDefinition(
        badge_id="centurion",
        name="Centurion",
        description="100-day conversation streak",
        category=BadgeCategory.MILESTONE,
        icon="🏛️",
        target_count=1,
        event_type=GameEventType.STREAK_MILESTONE,
        event_filter={"milestone_gte": 100},
        secret=True,
    ),
    BadgeDefinition(
        badge_id="searcher",
        name="Knowledge Seeker",
        description="Use web search 20 times",
        category=BadgeCategory.ACTION,
        icon="🔍",
        target_count=20,
        event_type=GameEventType.WEB_SEARCHED,
    ),
    BadgeDefinition(
        badge_id="habit_master",
        name="Habit Master",
        description="Log habits 50 times",
        category=BadgeCategory.MILESTONE,
        icon="💪",
        target_count=50,
        event_type=GameEventType.HABIT_LOGGED,
    ),
    BadgeDefinition(
        badge_id="first_quest",
        name="Quest Starter",
        description="Complete your first personal growth quest",
        category=BadgeCategory.MILESTONE,
        icon="🏆",
        target_count=1,
        event_type=GameEventType.QUEST_COMPLETED,
    ),
    BadgeDefinition(
        badge_id="social_butterfly",
        name="Social Butterfly",
        description="Refer a friend who signs up",
        category=BadgeCategory.SOCIAL,
        icon="🦋",
        target_count=1,
        event_type=GameEventType.REFERRAL_COMPLETED,
    ),
]

_BADGE_BY_ID: dict[str, BadgeDefinition] = {b.badge_id: b for b in BADGE_DEFINITIONS}


def _matches_filter(event: GameEvent, badge: BadgeDefinition) -> bool:
    """Check whether an event matches the badge's optional filter."""
    if not badge.event_filter:
        return True
    props = event.properties
    if "hour_before" in badge.event_filter:
        hour = props.get("hour", 99)
        if hour >= badge.event_filter["hour_before"]:
            return False
    if "milestone_gte" in badge.event_filter:
        milestone = props.get("milestone", 0)
        if milestone < badge.event_filter["milestone_gte"]:
            return False
    return True


async def _increment_and_check(
    session: AsyncSession,
    user_id: int,
    badge: BadgeDefinition,
) -> bool:
    """Increment badge progress and return True if just unlocked."""
    result = await session.execute(
        select(UserBadge).where(
            UserBadge.user_id == user_id,
            UserBadge.badge_id == badge.badge_id,
        )
    )
    ub = result.scalar_one_or_none()

    if ub is None:
        ub = UserBadge(
            user_id=user_id,
            badge_id=badge.badge_id,
            progress=0,
            unlocked=False,
        )
        session.add(ub)

    if ub.unlocked:
        return False  # Already unlocked

    ub.progress += 1
    if ub.progress >= badge.target_count:
        ub.unlocked = True
        ub.unlocked_at = datetime.now(timezone.utc)
        await session.flush()
        return True

    await session.flush()
    return False


async def _send_badge_celebration(user_id: int, badge: BadgeDefinition) -> None:
    """Send a Telegram celebration message for a newly unlocked badge."""
    try:
        async with AsyncSessionLocal() as session:
            user = await session.get(User, user_id)
            if not user:
                return

        message = (
            f"{badge.icon} <b>Badge Unlocked: {badge.name}!</b>\n\n"
            f"{badge.description}\n\n"
            f"Congratulations! Keep going! 🎉"
        )
        bot = Bot(
            token=settings.TELEGRAM_BOT_TOKEN,
            default=DefaultBotProperties(parse_mode="HTML"),
        )
        try:
            await bot.send_message(user.tg_chat_id, message)
        finally:
            await bot.session.close()
    except Exception:
        logger.exception("Failed to send badge celebration for user {}", user_id)


async def _on_badge_event(event: GameEvent) -> None:
    """Event bus listener: check all badges matching this event type."""
    if not settings.is_feature_enabled("F003_BADGES"):
        return

    matching = [
        b
        for b in BADGE_DEFINITIONS
        if b.event_type == event.event and _matches_filter(event, b)
    ]
    if not matching:
        return

    try:
        async with AsyncSessionLocal() as session:
            for badge in matching:
                just_unlocked = await _increment_and_check(
                    session, event.user_id, badge
                )
                if just_unlocked:
                    logger.info(
                        "User {} unlocked badge '{}'",
                        event.user_id,
                        badge.badge_id,
                    )
                    await event_bus.emit(
                        GameEvent(
                            event=GameEventType.BADGE_UNLOCKED,
                            user_id=event.user_id,
                            feature_id="F003",
                            properties={"badge_id": badge.badge_id},
                            timestamp=datetime.now(timezone.utc),
                        )
                    )
                    await _send_badge_celebration(event.user_id, badge)
            await session.commit()
    except Exception:
        logger.exception(
            "Badge processing failed for event {} user {}",
            event.event.value,
            event.user_id,
        )


async def get_user_badges(session: AsyncSession, user_id: int) -> list[dict]:
    """Return all badges with progress for a user (for /badges display)."""
    result = await session.execute(
        select(UserBadge).where(UserBadge.user_id == user_id)
    )
    user_badges = {ub.badge_id: ub for ub in result.scalars().all()}

    badges = []
    for badge in BADGE_DEFINITIONS:
        if badge.secret and badge.badge_id not in user_badges:
            continue  # Hide secret badges until unlocked
        ub = user_badges.get(badge.badge_id)
        badges.append(
            {
                "badge_id": badge.badge_id,
                "name": badge.name,
                "description": badge.description,
                "icon": badge.icon,
                "category": badge.category.value,
                "progress": ub.progress if ub else 0,
                "target": badge.target_count,
                "unlocked": ub.unlocked if ub else False,
                "secret": badge.secret,
            }
        )
    return badges


# ── Register listeners for all badge-triggering events ───────────
_BADGE_EVENT_TYPES = {b.event_type for b in BADGE_DEFINITIONS}
for _evt in _BADGE_EVENT_TYPES:
    event_bus.subscribe(_evt, _on_badge_event)
