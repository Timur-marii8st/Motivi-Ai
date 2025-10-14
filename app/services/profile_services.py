from __future__ import annotations
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from datetime import time
from ..models.users import User
from ..models.core_memory import CoreMemory

async def get_or_create_user(session: AsyncSession, tg_user_id: int, tg_chat_id: int) -> User:
    result = await session.execute(select(User).where(User.tg_user_id == tg_user_id))
    user = result.scalar_one_or_none()
    if user:
        return user
    user = User(tg_user_id=tg_user_id, tg_chat_id=tg_chat_id)
    session.add(user)
    await session.flush()
    # Ensure core memory row
    cm = CoreMemory(user_id=user.id, goals_json=None, sleep_schedule_json=None)
    session.add(cm)
    await session.flush()
    return user

async def update_user_profile(
    session: AsyncSession,
    user: User,
    name: Optional[str] = None,
    age: Optional[int] = None,
    timezone: Optional[str] = None,
    wake_time: Optional[time] = None,
    bed_time: Optional[time] = None,
    occupation_json: Optional[dict] = None,
) -> User:
    changed = False
    if name is not None:
        user.name = name; changed = True
    if age is not None:
        user.age = age; changed = True
    if timezone is not None:
        user.timezone = timezone; changed = True
    if wake_time is not None:
        user.wake_time = wake_time; changed = True
    if bed_time is not None:
        user.bed_time = bed_time; changed = True
    if occupation_json is not None:
        user.occupation_json = occupation_json; changed = True
    if changed:
        user.touch()
        session.add(user)
    return user