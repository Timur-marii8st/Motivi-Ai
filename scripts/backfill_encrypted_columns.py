"""
Utility script to re-save sensitive columns so that the new encrypted types
rewrite existing plaintext rows.

Usage:
    poetry run python scripts/backfill_encrypted_columns.py
"""

from __future__ import annotations

import asyncio
from typing import Iterable

from loguru import logger
from sqlalchemy import select, update, literal

from app.models.core_memory import CoreMemory
from app.models.working_memory import WorkingMemory, WorkingMemoryEntry
from app.models.episode import Episode
from app.models.task import Task
from app.models.habit import Habit, HabitLog
from app.models.users import User
from app.models.settings import UserSettings
from app.db import AsyncSessionLocal

DATABASE_URL="postgresql+asyncpg://postgres:S.H.E.L.Dq12@localhost:5432/motivi"


async def _backfill_columns(session, model, column_names: Iterable[str]) -> None:
    columns = [getattr(model, "id")] + [getattr(model, column) for column in column_names]
    result = await session.execute(select(*columns))

    total_updates = 0
    for row in result:
        row_id = row[0]
        updates = {}
        for idx, column_name in enumerate(column_names, start=1):
            value = row[idx]
            if value is not None:
                updates[column_name] = literal(value)
        if updates:
            await session.execute(
                update(model)
                .where(getattr(model, "id") == row_id)
                .values(**updates)
            )
            total_updates += 1

    logger.info("Backfilled %s rows in %s", total_updates, model.__tablename__)


async def main() -> None:
    async with AsyncSessionLocal() as session:
        await _backfill_columns(
            session,
            CoreMemory,
            ["core_text", "sleep_schedule_json"],
        )
        await _backfill_columns(
            session,
            WorkingMemory,
            ["working_memory_text"],
        )
        await _backfill_columns(
            session,
            WorkingMemoryEntry,
            ["working_memory_text"],
        )
        await _backfill_columns(
            session,
            Episode,
            ["text", "metadata_json"],
        )
        await _backfill_columns(
            session,
            Task,
            ["description"],
        )
        await _backfill_columns(
            session,
            Habit,
            ["description"],
        )
        await _backfill_columns(
            session,
            HabitLog,
            ["note"],
        )
        await _backfill_columns(
            session,
            User,
            ["name", "occupation_json"],
        )
        await _backfill_columns(
            session,
            UserSettings,
            ["summary_preferences_json"],
        )
        await session.commit()


if __name__ == "__main__":
    asyncio.run(main())

