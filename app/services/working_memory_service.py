from __future__ import annotations
from typing import Optional
from datetime import datetime, date, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from loguru import logger

from ..models.working_memory import WorkingMemory

class WorkingMemoryService:
    """
    Manage short-term goals and summaries; weekly refresh.
    """

    @staticmethod
    async def get_or_create(session: AsyncSession, user_id: int) -> WorkingMemory:
        result = await session.execute(select(WorkingMemory).where(WorkingMemory.user_id == user_id))
        wm = result.scalar_one_or_none()
        if not wm:
            wm = WorkingMemory(
                user_id=user_id,
                focus_summary=None,
                short_term_goals_json=None,
                decay_date=date.today() + timedelta(days=7),
            )
            session.add(wm)
            await session.flush()
        return wm

    @staticmethod
    async def update_focus(
        session: AsyncSession, user_id: int, summary: str, goals: Optional[dict] = None
    ) -> WorkingMemory:
        wm = await WorkingMemoryService.get_or_create(session, user_id)
        wm.focus_summary = summary
        if goals is not None:
            wm.short_term_goals_json = goals
        wm.updated_at = datetime.utcnow()
        session.add(wm)
        return wm

    @staticmethod
    async def refresh_weekly(session: AsyncSession, user_id: int, new_summary: str, new_goals: dict):
        """
        Called by weekly job: reset decay date, update summary/goals.
        """
        wm = await WorkingMemoryService.get_or_create(session, user_id)
        wm.focus_summary = new_summary
        wm.short_term_goals_json = new_goals
        wm.decay_date = date.today() + timedelta(days=7)
        wm.updated_at = datetime.utcnow()
        session.add(wm)
        logger.info("Working memory refreshed for user {}", user_id)

    @staticmethod
    async def is_stale(session: AsyncSession, user_id: int) -> bool:
        wm = await WorkingMemoryService.get_or_create(session, user_id)
        if not wm.decay_date:
            return True
        return date.today() >= wm.decay_date