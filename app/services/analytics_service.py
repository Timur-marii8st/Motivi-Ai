"""Analytics sink — persists every GameEvent to the gamification_events table.

Registered as a global listener on the event bus so every domain event
is automatically recorded for audit and reporting.
"""
from __future__ import annotations

from loguru import logger
from sqlmodel import select

from app.db import AsyncSessionLocal
from app.models.gamification import GamificationEvent
from app.services.gamification.schemas import GameEvent


async def persist_event(event: GameEvent) -> None:
    """Write a GameEvent to the DB.  Runs inside its own session."""
    try:
        async with AsyncSessionLocal() as session:
            row = GamificationEvent(
                user_id=event.user_id,
                event_type=event.event.value,
                feature_id=event.feature_id,
                properties_json=event.properties,
            )
            session.add(row)
            await session.commit()
    except Exception:
        logger.exception("Failed to persist analytics event {}", event.event.value)


async def count_events_today(user_id: int, event_type: str) -> int:
    """Count how many events of a given type a user has emitted today (UTC)."""
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)

    try:
        async with AsyncSessionLocal() as session:
            from sqlalchemy import func
            stmt = (
                select(func.count())
                .select_from(GamificationEvent)
                .where(
                    GamificationEvent.user_id == user_id,
                    GamificationEvent.event_type == event_type,
                    GamificationEvent.created_at >= start_of_day,
                )
            )
            result = await session.execute(stmt)
            return result.scalar_one()
    except Exception:
        logger.exception("Failed to count events for user_id={}", user_id)
        return 0
