import asyncio

from sqlmodel import SQLModel, select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.models.working_memory import WorkingMemoryEntry
from app.services.working_memory_service import WorkingMemoryService


class DummyEmb:
    async def embed(self, text, task_type=None):
        # return a fixed-dimension dummy vector
        return [0.0] * 1536


async def _run_test():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSessionLocal() as session:
        service = WorkingMemoryService(embeddings=DummyEmb())

        # insert 9 entries; service should keep only last 7
        for i in range(9):
            await service.store_working(session=session, user_id=1, fact_text=f"fact {i}")

        res = await session.execute(
            select(WorkingMemoryEntry).where(WorkingMemoryEntry.user_id == 1).order_by(WorkingMemoryEntry.history_order.asc())
        )
        entries = res.scalars().all()

        assert len(entries) == 7, f"Expected 7 entries, got {len(entries)}"
        assert entries[0].working_memory_text == "fact 8"
        assert [e.history_order for e in entries] == [1, 2, 3, 4, 5, 6, 7]


def test_working_memory_history():
    asyncio.run(_run_test())
