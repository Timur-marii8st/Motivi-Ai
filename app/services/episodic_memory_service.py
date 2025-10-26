from __future__ import annotations
from typing import List, Optional
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, and_
from loguru import logger

from ..models.episode import Episode, EpisodeEmbedding
from ..embeddings.gemini_embedding_client import GeminiEmbeddings
from ..config import settings

class EpisodicMemoryService:
    """
    Archive past events, vectorize them, and retrieve via semantic search.
    """

    def __init__(self, embeddings: GeminiEmbeddings):
        self.embeddings = embeddings

    async def store_episode(
        self,
        session: AsyncSession,
        user_id: int,
        type: str,
        fact_text: str,
        metadata: Optional[dict] = None,
    ) -> Episode:
        """
        Store an episode and generate its embedding.
        """
        # set created_at on Episode model; expiry handled at retrieval time using settings
        ep = Episode(user_id=user_id, type=type, text=fact_text, metadata_json=metadata or {})
        session.add(ep)
        await session.flush()  # Get ep.id

        # Generate embedding
        try:
            emb_vector = await self.embeddings.embed(fact_text, task_type="retrieval_document")
            if not emb_vector:
                raise ValueError("Empty embedding returned")
            ep_emb = EpisodeEmbedding(episode_id=ep.id, embedding=emb_vector)
            session.add(ep_emb)
            await session.flush()
            logger.info("Episode {} vectorized and stored for user {}", ep.id, user_id)
        except Exception as e:
            logger.error("Failed to embed episode {}: {}", ep.id, e)
            # Store episode anyway; embedding can be retried later

        return ep

    async def retrieve_similar(
        self,
        session: AsyncSession,
        user_id: int,
        query_text: str,
        top_k: int = 5,
        days_back: Optional[int] = None,
    ) -> List[Episode]:
        """
        RAG retrieval: find top-k semantically similar episodes.
        """
        # Embed query
        query_vec = await self.embeddings.embed(query_text, task_type="retrieval_query")
        if not query_vec:
            logger.warning("Query embedding failed; returning empty results")
            return []

        # Build filters
        filters = [Episode.user_id == user_id]

        # Enforce episode lifetime from settings if days_back not explicitly provided
        life_days = settings.EPISODE_LIFETIME_DAYS
        if days_back:
            cutoff = datetime.utcnow() - timedelta(days=days_back)
        else:
            # EPISODE_LIFETIME_DAYS may be float (e.g., 75.0); convert to timedelta using days
            cutoff = datetime.utcnow() - timedelta(days=float(life_days))
        filters.append(Episode.created_at >= cutoff)

        # Cosine similarity search with pgvector
        # We'll join Episode with EpisodeEmbedding and order by <=> (cosine distance)
        stmt = (
            select(Episode)
            .join(EpisodeEmbedding, Episode.id == EpisodeEmbedding.episode_id)
            .where(and_(*filters))
            .order_by(EpisodeEmbedding.embedding.cosine_distance(query_vec))
            .limit(top_k)
        )

        result = await session.execute(stmt)
        episodes = result.scalars().all()
        return list(episodes)

    async def get_recent_episodes(
        self, session: AsyncSession, user_id: int, limit: int = 10, type_filter: Optional[str] = None
    ) -> List[Episode]:
        """Fallback: retrieve most recent episodes (no semantic search)."""
        filters = [Episode.user_id == user_id]
        if type_filter:
            filters.append(Episode.type == type_filter)

        stmt = select(Episode).where(and_(*filters)).order_by(Episode.created_at.desc()).limit(limit)
        result = await session.execute(stmt)
        return list(result.scalars().all())