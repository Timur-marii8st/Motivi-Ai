"""Conversation streak tracking with freeze-token mechanics.

Timezone-aware: always works with the user's LOCAL date.
"""
from __future__ import annotations

from datetime import date, datetime, timezone, timedelta

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.users import User
from app.services.event_bus import event_bus
from app.services.gamification.schemas import (
    GameEvent,
    GameEventType,
    STREAK_FREEZE_AWARD_INTERVAL,
    STREAK_FREEZE_MAX,
    STREAK_MILESTONES,
)


class StreakService:
    """Manages conversation streaks and freeze tokens."""

    @staticmethod
    async def update_streak(
        session: AsyncSession,
        user: User,
        user_local_date: date,
    ) -> dict:
        """Update the user's conversation streak based on their local date.

        Returns a dict with streak state and any events that occurred.
        """
        if not settings.is_feature_enabled("F006_STREAKS"):
            return {
                "streak_count": user.streak_count,
                "freeze_used": False,
                "freeze_tokens": user.streak_freeze_tokens,
                "milestone": None,
            }

        freeze_used = False
        milestone = None
        yesterday = user_local_date - timedelta(days=1)

        if user.last_active_date == user_local_date:
            # Already counted today — no-op
            return {
                "streak_count": user.streak_count,
                "freeze_used": False,
                "freeze_tokens": user.streak_freeze_tokens,
                "milestone": None,
            }

        if user.last_active_date is None:
            # First ever interaction
            user.streak_count = 1
            logger.info("User {} started first streak", user.id)

        elif user.last_active_date == yesterday:
            # Consecutive day — extend streak
            user.streak_count += 1
            logger.info("User {} streak extended to {}", user.id, user.streak_count)

            # Award freeze token at intervals
            if (
                user.streak_count % STREAK_FREEZE_AWARD_INTERVAL == 0
                and user.streak_freeze_tokens < STREAK_FREEZE_MAX
            ):
                user.streak_freeze_tokens += 1
                logger.info(
                    "User {} earned freeze token (now {})",
                    user.id,
                    user.streak_freeze_tokens,
                )

            # Check for milestone
            if user.streak_count in STREAK_MILESTONES:
                milestone = user.streak_count
                logger.info("User {} hit streak milestone: {}", user.id, milestone)
                await event_bus.emit(
                    GameEvent(
                        event=GameEventType.STREAK_MILESTONE,
                        user_id=user.id,
                        feature_id="F006",
                        properties={"milestone": milestone},
                        timestamp=datetime.now(timezone.utc),
                    )
                )

        elif user.last_active_date < yesterday:
            # Missed one or more days
            if user.streak_freeze_tokens > 0:
                user.streak_freeze_tokens -= 1
                freeze_used = True
                user.streak_count += 1
                logger.info(
                    "User {} used freeze token (remaining: {}), streak preserved at {}",
                    user.id,
                    user.streak_freeze_tokens,
                    user.streak_count,
                )
            else:
                old = user.streak_count
                user.streak_count = 1
                logger.info(
                    "User {} streak reset from {} to 1 (no freeze tokens)",
                    user.id,
                    old,
                )

        user.last_active_date = user_local_date
        user.touch()
        session.add(user)

        # Emit streak update event
        await event_bus.emit(
            GameEvent(
                event=GameEventType.STREAK_UPDATED,
                user_id=user.id,
                feature_id="F006",
                properties={
                    "streak_count": user.streak_count,
                    "freeze_used": freeze_used,
                },
                timestamp=datetime.now(timezone.utc),
            )
        )

        return {
            "streak_count": user.streak_count,
            "freeze_used": freeze_used,
            "freeze_tokens": user.streak_freeze_tokens,
            "milestone": milestone,
        }

    @staticmethod
    def get_streak_display(user: User) -> str:
        """Format streak for display in morning check-in and /profile."""
        if not settings.is_feature_enabled("F006_STREAKS"):
            return ""
        if user.streak_count <= 0:
            return ""
        return (
            f"🔥 Streak: {user.streak_count} days | "
            f"❄️ Freezes: {user.streak_freeze_tokens}"
        )

    @staticmethod
    async def freeze_streak_for_break(session: AsyncSession, user: User) -> None:
        """Protect the streak when break mode is activated.

        Sets last_active_date to today so the streak won't break
        during the break period without consuming a freeze token.
        """
        if not settings.is_feature_enabled("F006_STREAKS"):
            return
        logger.info("Freezing streak for user {} during break mode", user.id)
        # We keep the streak intact by not resetting it.
        # The break mode check in jobs.py will skip streak updates.
