"""
Utility script to re-save sensitive columns so that the new encrypted types
rewrite existing plaintext rows.

Usage:
    poetry run python scripts/backfill_encrypted_columns.py
"""

from __future__ import annotations

import asyncio
from typing import Iterable, Type

from loguru import logger
from sqlalchemy import select, update
from sqlmodel import SQLModel

from app.models.core_memory import CoreMemory
from app.models.working_memory import WorkingMemory, WorkingMemoryEntry
from app.models.episode import Episode
from app.models.habit import Habit, HabitLog
from app.models.users import User
from app.models.settings import UserSettings
from app.db import AsyncSessionLocal


async def _backfill_table(session_factory, model: Type[SQLModel], column_names: Iterable[str]) -> None:
    """
    Backfills a table using Keyset Pagination (iterating by ID).
    We create a NEW session for each batch to ensure clean transaction state and no memory bloat.
    """
    BATCH_SIZE = 1000
    last_seen_id = 0
    total_processed = 0

    logger.info("Starting backfill for table: {}", model.__tablename__)

    while True:
        # Create a fresh session for each batch to keep memory usage low (clear Identity Map)
        async with session_factory() as session:
            # 1. Fetch a batch of rows greater than last_seen_id
            # We select ID + relevant columns.
            cols = [model.id] + [getattr(model, c) for c in column_names]
            
            statement = (
                select(*cols)
                .where(model.id > last_seen_id)
                .order_by(model.id.asc())
                .limit(BATCH_SIZE)
            )
            
            result = await session.execute(statement)
            rows = result.all()

            if not rows:
                break  # Done

            batch_updates = 0
            
            for row in rows:
                row_id = row[0]
                last_seen_id = row_id # Track last ID for next iteration
                
                updates = {}
                # Check columns (indices shifted by 1 because ID is index 0)
                for i, col_name in enumerate(column_names, start=1):
                    val = row[i]
                    if val is not None:
                        # Re-assigning the same value triggers the EncryptedType serializer
                        # The 'val' here is already decrypted (plaintext) by process_result_value
                        # The update() below will re-encrypt it via process_bind_param
                        updates[col_name] = val
                
                if updates:
                    # Execute individual update to trigger SQLAlchemy's type processing
                    await session.execute(
                        update(model)
                        .where(model.id == row_id)
                        .values(**updates)
                    )
                    batch_updates += 1

            # Commit this batch
            if batch_updates > 0:
                await session.commit()
                total_processed += batch_updates
                logger.info("  - Table {}: processed rows up to ID {} (Batch updates: {})", 
                           model.__tablename__, last_seen_id, batch_updates)
            
            # If we got fewer rows than limit, we are done
            if len(rows) < BATCH_SIZE:
                break

    logger.info("Finished {}. Total updated: {}", model.__tablename__, total_processed)


async def main() -> None:
    # We pass the session factory (AsyncSessionLocal), not an instance.
    try:
        await _backfill_table(AsyncSessionLocal, CoreMemory, ["core_text", "sleep_schedule_json"])
        await _backfill_table(AsyncSessionLocal, WorkingMemory, ["working_memory_text"])
        await _backfill_table(AsyncSessionLocal, WorkingMemoryEntry, ["working_memory_text"])
        await _backfill_table(AsyncSessionLocal, Episode, ["text", "metadata_json"])
        await _backfill_table(AsyncSessionLocal, Habit, ["description"])
        await _backfill_table(AsyncSessionLocal, HabitLog, ["note"])
        await _backfill_table(AsyncSessionLocal, User, ["name", "occupation_json"])
        await _backfill_table(AsyncSessionLocal, UserSettings, ["summary_preferences_json"])
    except Exception as e:
        logger.exception("Fatal error during backfill: {}", e)

if __name__ == "__main__":
    asyncio.run(main())