from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import update
from sqlmodel import select

from app.db import AsyncSessionLocal
from app.models.working_memory import WorkingMemory
from app.security.row_integrity import calculate_integrity_signature


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Repair working-memory signatures after the legacy cleanup job "
            "updated rows without re-signing them."
        )
    )
    parser.add_argument("--user-id", type=int, default=None)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist repairs. Without this flag the command is a dry run.",
    )
    return parser.parse_args()


async def repair(*, user_id: int | None, apply_changes: bool) -> tuple[int, int]:
    table = WorkingMemory.__table__
    stmt = select(
        table.c.id,
        table.c.user_id,
        table.c.working_memory_text,
        table.c.integrity_sig,
    )
    if user_id is not None:
        stmt = stmt.where(table.c.user_id == user_id)

    checked = 0
    mismatched = 0
    async with AsyncSessionLocal() as session:
        result = await session.execute(stmt)
        for row_id, owner_id, memory_text, current_sig in result.all():
            checked += 1
            expected_sig = calculate_integrity_signature(
                WorkingMemory.__tablename__,
                int(owner_id),
                {"working_memory_text": memory_text},
            )
            if current_sig == expected_sig:
                continue

            mismatched += 1
            print(f"working_memory id={row_id} user_id={owner_id}: mismatch")
            if apply_changes:
                await session.execute(
                    update(table)
                    .where(table.c.id == row_id)
                    .values(integrity_sig=expected_sig)
                )

        if apply_changes:
            await session.commit()
        else:
            await session.rollback()

    return checked, mismatched


async def main() -> None:
    args = parse_args()
    checked, mismatched = await repair(
        user_id=args.user_id,
        apply_changes=args.apply,
    )
    mode = "applied" if args.apply else "dry-run"
    print(f"{mode}: checked={checked} mismatched={mismatched}")


if __name__ == "__main__":
    asyncio.run(main())
