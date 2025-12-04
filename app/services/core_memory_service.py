from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from ..models.core_memory import CoreMemory, CoreEmbedding, CoreFact, CoreFactEmbedding
from datetime import datetime, timezone
import json
from typing import Optional
from loguru import logger
from ..embeddings.gemini_embedding_client import GeminiEmbeddings
from typing import List

class CoreMemoryService:
    """Manage fundamental, unchanging user data: goals, sleep schedule."""
    def __init__(self, embeddings: GeminiEmbeddings | None = None):
        # allow injection for tests; create default client when not provided
        self.embeddings = embeddings or GeminiEmbeddings()

    @staticmethod
    async def get_or_create(session: AsyncSession, user_id: int) -> CoreMemory:
        result = await session.execute(select(CoreMemory).where(CoreMemory.user_id == user_id))
        cm = result.scalar_one_or_none()
        if not cm:
            cm = CoreMemory(user_id=user_id, sleep_schedule_json=None)
            session.add(cm)
            await session.flush()
        return cm

    @staticmethod
    async def update_goals(session: AsyncSession, user_id: int, goals: dict) -> CoreMemory:
        cm = await CoreMemoryService.get_or_create(session, user_id)
        # store timezone-aware UTC datetime
        cm.updated_at = datetime.now(timezone.utc)
        session.add(cm)
        return cm

    @staticmethod
    async def update_sleep_schedule(session: AsyncSession, user_id: int, schedule: dict) -> CoreMemory:
        cm = await CoreMemoryService.get_or_create(session, user_id)
        cm.sleep_schedule_json = schedule
        cm.updated_at = datetime.now(timezone.utc)
        session.add(cm)
        return cm
    
    async def store_core(
        self,
        session: AsyncSession,
        user_id: int,
        fact_text: str,
        metadata: Optional[dict] = None,
    ) -> CoreMemory:
        """
        Store an episode and generate its embedding.
        """
        # get or create user's core memory row
        cm = await CoreMemoryService.get_or_create(session, user_id)

        # Insert a new CoreFact row representing this fact
        fact = CoreFact(core_memory_id=cm.id, fact_text=fact_text)
        session.add(fact)
        await session.flush()  # ensure fact.id is available
        # Don't change created_at (date of CoreMemory creation). We always update updated_at.
        cm.updated_at = datetime.now(timezone.utc)
        session.add(cm)
        await session.flush()  # ensure cm.id is available

        # Generate embedding and store/update per-fact embedding (CoreFactEmbedding)
        try:
            emb_vector = await self.embeddings.embed(fact_text, task_type="retrieval_document")
            if not emb_vector:
                raise ValueError("Empty embedding returned")
            # Try to find existing embedding for this core fact
            result = await session.execute(select(CoreFactEmbedding).where(CoreFactEmbedding.core_fact_id == fact.id))
            existing = result.scalar_one_or_none()
            if existing:
                existing.embedding = emb_vector
                existing.created_at = datetime.now(timezone.utc)
                session.add(existing)
                await session.flush()
                logger.info("Updated embedding for core_fact {} (user {})", fact.id, user_id)
            else:
                emb = CoreFactEmbedding(core_fact_id=fact.id, embedding=emb_vector)
                session.add(emb)
                await session.flush()
                logger.info("Stored embedding for core_fact {} (user {})", fact.id, user_id)
        except Exception as e:
            logger.error("Failed to embed core memory for user {}: {}", user_id, e)

        return cm

    async def retrieve_similar(
        self,
        session: AsyncSession,
        user_id: int,
        query_text: str,
        top_k: int = 5,
    ) -> List[CoreFact]:
        """Return top-k CoreFact objects semantically similar to query_text.

        If user_id is provided, restrict to that user's core memory facts.
        """
        query_vec = await self.embeddings.embed(query_text, task_type="retrieval_query")
        if not query_vec:
            logger.warning("Query embedding failed; returning empty results")
            return []


        # Filter to facts for the user via join through CoreMemory
        filters = [CoreMemory.id == CoreFact.core_memory_id]
        if user_id is not None:
            filters.append(CoreMemory.user_id == user_id)

        # join core facts with their embeddings and order by cosine distance
        stmt = (
            select(CoreFact)
            .join(CoreFactEmbedding, CoreFact.id == CoreFactEmbedding.core_fact_id)
            .join(CoreMemory, CoreMemory.id == CoreFact.core_memory_id)
            .where(*filters)
        )

        # apply ordering and limit
        stmt = stmt.order_by(CoreFactEmbedding.embedding.cosine_distance(query_vec)).limit(top_k)

        result = await session.execute(stmt)
        rows = result.scalars().all()
        return list(rows)

    async def list_facts_for_user(self, session: AsyncSession, user_id: int) -> List[CoreFact]:
        """Return all core facts for a given user."""
        stmt = select(CoreFact).join(CoreMemory, CoreMemory.id == CoreFact.core_memory_id).where(CoreMemory.user_id == user_id)
        result = await session.execute(stmt)
        return result.scalars().all()