from __future__ import annotations
from typing import Optional
from datetime import datetime, timezone, date, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from loguru import logger

from ..models.working_memory import WorkingMemory
from ..models.working_memory import WorkingEmbedding
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
                focus_summary=None,
                short_term_goals_json=None,
                decay_date=date.today() + timedelta(days=int(settings.WORKING_MEMORY_LIFETIME_DAYS)),
            )
            session.add(wm)
            await session.flush()
        return wm

    @staticmethod
    async def refresh_weekly(session: AsyncSession, user_id: int, new_summary: str, new_goals: dict):
        """
        Called by weekly job: reset decay date, update summary/goals.
        """
        wm = await WorkingMemoryService.get_or_create(session, user_id)
        wm.focus_summary = new_summary
        wm.short_term_goals_json = new_goals
        wm.decay_date = date.today() + timedelta(days=int(settings.WORKING_MEMORY_LIFETIME_DAYS))
        wm.updated_at = datetime.now(timezone.utc)
        session.add(wm)
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
        Store or update working memory summary and create/update its embedding.
        """
        wm = await WorkingMemoryService.get_or_create(session, user_id)

        # update focus_summary with provided text (best-effort)
        wm.focus_summary = fact_text
        wm.updated_at = datetime.now(timezone.utc)
        session.add(wm)
        await session.flush()

        # generate embedding and store one-per-working-memory
        try:
            emb_vector = await self.embeddings.embed(fact_text, task_type="retrieval_document")
            if not emb_vector:
                raise ValueError("Empty embedding returned")

            result = await session.execute(select(WorkingEmbedding).where(WorkingEmbedding.working_memory_id == wm.id))
            existing = result.scalar_one_or_none()
            if existing:
                existing.embedding = emb_vector
                existing.created_at = datetime.now(timezone.utc)
                session.add(existing)
                await session.flush()
                logger.info("Updated embedding for working_memory {} (user {})", wm.id, user_id)
            else:
                emb = WorkingEmbedding(working_memory_id=wm.id, embedding=emb_vector)
                session.add(emb)
                await session.flush()
                logger.info("Stored embedding for working_memory {} (user {})", wm.id, user_id)
        except Exception as e:
            logger.error("Failed to embed working memory for user {}: {}", user_id, e)

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