from __future__ import annotations

import asyncio

from sqlmodel import select

from app.db import AsyncSessionLocal
from app.models.core_memory import CoreMemory
from app.models.episode import Episode
from app.models.habit import Habit
from app.models.plan import Plan
from app.models.settings import UserSettings
from app.models.userbot_session import UserBotSession
from app.models.users import User
from app.models.working_memory import WorkingMemory, WorkingMemoryEntry
from app.security.row_integrity import recalculate_integrity_signature


MODELS = (
    User,
    CoreMemory,
    WorkingMemory,
    WorkingMemoryEntry,
    Episode,
    UserSettings,
    Habit,
    Plan,
    UserBotSession,
)


async def main() -> None:
    async with AsyncSessionLocal() as session:
        for model in MODELS:
            result = await session.execute(select(model))
            rows = result.scalars().all()
            for row in rows:
                recalculate_integrity_signature(row)
                session.add(row)
            await session.commit()
            print(f"Backfilled integrity signatures for {model.__name__}: {len(rows)}")


if __name__ == "__main__":
    asyncio.run(main())
