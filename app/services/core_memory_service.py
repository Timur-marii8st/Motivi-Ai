from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from ..models.core_memory import CoreMemory

class CoreMemoryService:
    """Manage fundamental, unchanging user data: goals, sleep schedule."""

    @staticmethod
    async def get_or_create(session: AsyncSession, user_id: int) -> CoreMemory:
        result = await session.execute(select(CoreMemory).where(CoreMemory.user_id == user_id))
        cm = result.scalar_one_or_none()
        if not cm:
            cm = CoreMemory(user_id=user_id, goals_json=None, sleep_schedule_json=None)
            session.add(cm)
            await session.flush()
        return cm

    @staticmethod
    async def update_goals(session: AsyncSession, user_id: int, goals: dict) -> CoreMemory:
        cm = await CoreMemoryService.get_or_create(session, user_id)
        cm.goals_json = goals
        cm.updated_at = datetime.utcnow()
        session.add(cm)
        return cm

    @staticmethod
    async def update_sleep_schedule(session: AsyncSession, user_id: int, schedule: dict) -> CoreMemory:
        cm = await CoreMemoryService.get_or_create(session, user_id)
        cm.sleep_schedule_json = schedule
        cm.updated_at = datetime.utcnow()
        session.add(cm)
        return cm

from datetime import datetime