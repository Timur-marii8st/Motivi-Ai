"""Post-message gamification handler.

Called after every successful chat message to update streaks,
check milestones, and emit events. All errors are caught and logged —
this must never crash the chat handler.
"""
from __future__ import annotations

from datetime import datetime, timezone

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from zoneinfo import ZoneInfo

from app.config import settings
from app.models.users import User
from app.services.event_bus import event_bus
from app.services.gamification.schemas import GameEvent, GameEventType


async def handle_post_message_gamification(
    session: AsyncSession,
    user: User,
    chat_id: int,
) -> None:
    """Run all post-message gamification logic.

    Called from chat.py after a successful LLM response.
    Every sub-step is individually try/except-guarded.
    """
    # 1. Emit MESSAGE_SENT event
    try:
        await event_bus.emit(
            GameEvent(
                event=GameEventType.MESSAGE_SENT,
                user_id=user.id,
                feature_id="F002",
                properties={},
                timestamp=datetime.now(timezone.utc),
            )
        )
    except Exception:
        logger.exception("Failed to emit MESSAGE_SENT for user {}", user.id)

    # 2. Update conversation streak
    try:
        from app.services.streak_service import StreakService

        tz_name = user.user_timezone or "UTC"
        try:
            user_tz = ZoneInfo(tz_name)
        except Exception:
            user_tz = ZoneInfo("UTC")

        user_local_date = datetime.now(timezone.utc).astimezone(user_tz).date()
        result = await StreakService.update_streak(session, user, user_local_date)

        if result.get("freeze_used"):
            logger.info(
                "Streak freeze used for user {} (streak: {})",
                user.id,
                result["streak_count"],
            )
    except Exception:
        logger.exception("Failed to update streak for user {}", user.id)

    # 3. Check memory milestones
    try:
        from app.services.milestone_service import MilestoneService

        await MilestoneService.check_memory_milestone(session, user, chat_id)
    except Exception:
        logger.exception(
            "Failed to check memory milestone for user {}", user.id
        )
