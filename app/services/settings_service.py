from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from ..models.settings import UserSettings

class SettingsService:
    @staticmethod
    async def get_or_create(session: AsyncSession, user_id: int) -> UserSettings:
        result = await session.execute(select(UserSettings).where(UserSettings.user_id == user_id))
        s = result.scalar_one_or_none()
        if not s:
            s = UserSettings(user_id=user_id)
            session.add(s)
            await session.flush()
        return s