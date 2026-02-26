from __future__ import annotations
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from loguru import logger

from ..models.user_trigger import UserTrigger


class UserTriggerService:
    MAX_TRIGGERS_PER_USER = 5

    @staticmethod
    async def list_triggers(session: AsyncSession, user_id: int) -> List[UserTrigger]:
        result = await session.execute(
            select(UserTrigger)
            .where(UserTrigger.user_id == user_id)
            .order_by(UserTrigger.created_at)
        )
        return list(result.scalars().all())

    @staticmethod
    async def create_trigger(
        session: AsyncSession,
        user_id: int,
        name: str,
        prompt: str,
        cron_hour: int,
        cron_minute: int = 0,
        cron_weekdays: Optional[str] = None,
    ) -> UserTrigger:
        # Enforce per-user limit
        result = await session.execute(
            select(UserTrigger).where(UserTrigger.user_id == user_id)
        )
        existing = list(result.scalars().all())
        if len(existing) >= UserTriggerService.MAX_TRIGGERS_PER_USER:
            raise ValueError(
                f"Maximum {UserTriggerService.MAX_TRIGGERS_PER_USER} triggers per user allowed."
            )

        trigger = UserTrigger(
            user_id=user_id,
            name=name,
            prompt=prompt,
            cron_hour=cron_hour,
            cron_minute=cron_minute,
            cron_weekdays=cron_weekdays,
        )
        session.add(trigger)
        await session.flush()
        logger.info("Created trigger {} for user {}", trigger.id, user_id)
        return trigger

    @staticmethod
    async def delete_trigger(session: AsyncSession, trigger_id: int, user_id: int) -> bool:
        trigger = await session.get(UserTrigger, trigger_id)
        if not trigger or trigger.user_id != user_id:
            return False
        await session.delete(trigger)
        await session.flush()
        logger.info("Deleted trigger {} for user {}", trigger_id, user_id)
        return True

    @staticmethod
    async def toggle_trigger(
        session: AsyncSession, trigger_id: int, user_id: int
    ) -> Optional[UserTrigger]:
        trigger = await session.get(UserTrigger, trigger_id)
        if not trigger or trigger.user_id != user_id:
            return None
        trigger.active = not trigger.active
        trigger.touch()
        session.add(trigger)
        await session.flush()
        return trigger
