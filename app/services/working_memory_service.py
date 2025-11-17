from __future__ import annotations
from typing import Optional
from datetime import datetime, timezone, date, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete
from sqlmodel import select
from loguru import logger

from ..models.working_memory import (
    WorkingMemory,
    WorkingEmbedding,
    WorkingMemoryEntry,
    WorkingEntryEmbedding,
)
from ..embeddings.gemini_embedding_client import GeminiEmbeddings
from typing import List
from ..config import settings

class WorkingMemoryService:
    """
    Manage short-term goals and summaries; weekly refresh.
    """
    def __init__(self, embeddings: GeminiEmbeddings | None = None):
        self.embeddings = embeddings or GeminiEmbeddings()

    @staticmethod
    async def get_or_create(session: AsyncSession, user_id: int) -> WorkingMemory:
        result = await session.execute(select(WorkingMemory).where(WorkingMemory.user_id == user_id))
        wm = result.scalar_one_or_none()
        if not wm:
            # use configured lifetime days for decay_date
            wm = WorkingMemory(
                user_id=user_id,
                working_memory_text=None,
                history_order=1,
                decay_date=date.today() + timedelta(days=int(settings.WORKING_MEMORY_LIFETIME_DAYS)),
            )
            session.add(wm)
            await session.flush()
        return wm

    @staticmethod
    async def refresh_weekly(session: AsyncSession, user_id: int, new_summary: str, new_goals: dict):
        """
        Called by weekly job: add new summary while maintaining history.
        """
        working_service = WorkingMemoryService()
        await working_service.store_working(
            session=session,
            user_id=user_id,
            fact_text=new_summary
        )
        logger.info("Working memory refreshed for user {}", user_id)

    @staticmethod
    async def is_stale(session: AsyncSession, user_id: int) -> bool:
        wm = await WorkingMemoryService.get_or_create(session, user_id)
        if not wm.decay_date:
            return True
        # if decay_date was set in the past or now, it's stale
        return date.today() >= wm.decay_date

    async def store_working(
        self,
        session: AsyncSession,
        user_id: int,
        fact_text: str,
        metadata: Optional[dict] = None,
    ) -> WorkingMemory:
        """
        Store working memory text while maintaining history of last 7 entries.
        """
        # Get existing entry rows for this user ordered by history_order (1 = newest)
        res = await session.execute(
            select(WorkingMemoryEntry)
            .where(WorkingMemoryEntry.user_id == user_id)
            .order_by(WorkingMemoryEntry.history_order.asc())
        )
        existing_entries = res.scalars().all()

        # Increment history_order for existing entries (1->2, 2->3, ...)
        for entry in existing_entries[:6]:
            entry.history_order = (entry.history_order or 0) + 1
            session.add(entry)

        # Delete entries beyond the 7th (those with index >=6)
        # First delete associated embeddings to avoid foreign key constraint violation
        for old in existing_entries[6:]:
            # Delete associated embeddings first
            await session.execute(
                delete(WorkingEntryEmbedding).where(
                    WorkingEntryEmbedding.working_entry_id == old.id
                )
            )
            # Then delete the entry
            await session.delete(old)

        # Create new entry as newest (history_order=1)
        new_entry = WorkingMemoryEntry(
            user_id=user_id,
            working_memory_text=fact_text,
            history_order=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        session.add(new_entry)
        await session.flush()

        # generate embedding for the new entry
        try:
            emb_vector = await self.embeddings.embed(fact_text, task_type="retrieval_document")
            if not emb_vector:
                raise ValueError("Empty embedding returned")

            emb = WorkingEntryEmbedding(
                working_entry_id=new_entry.id,
                embedding=emb_vector,
                created_at=datetime.now(timezone.utc),
            )
            session.add(emb)
            await session.flush()
            logger.info("Stored embedding for working_memory_entry {} (user {})", new_entry.id, user_id)
        except Exception as e:
            logger.error("Failed to embed working memory entry for user {}: {}", user_id, e)

        # Update the summary row (single WorkingMemory) so existing callers still get a quick summary
        wm = await WorkingMemoryService.get_or_create(session, user_id)
        wm.working_memory_text = fact_text
        wm.decay_date = date.today() + timedelta(days=int(settings.WORKING_MEMORY_LIFETIME_DAYS))
        wm.updated_at = datetime.now(timezone.utc)
        session.add(wm)
        await session.flush()

        return wm

    async def retrieve_similar(
        self,
        session: AsyncSession,
        user_id: int,
        query_text: str,
        top_k: int = 5,
    ) -> List[WorkingMemory]:
        query_vec = await self.embeddings.embed(query_text, task_type="retrieval_query")
        if not query_vec:
            logger.warning("Query embedding failed; returning empty results")
            return []

        filters = []
        if user_id is not None:
            filters.append(WorkingMemory.user_id == user_id)

        stmt = (
            select(WorkingMemory)
            .join(WorkingEmbedding, WorkingMemory.id == WorkingEmbedding.working_memory_id)
            .where(*filters) if filters else select(WorkingMemory).join(WorkingEmbedding, WorkingMemory.id == WorkingEmbedding.working_memory_id)
        )

        stmt = stmt.order_by(WorkingEmbedding.embedding.cosine_distance(query_vec)).limit(top_k)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return list(rows)