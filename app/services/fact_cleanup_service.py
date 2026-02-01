from __future__ import annotations

from typing import List, Any
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, select, and_, or_, exists
from sqlalchemy.orm import aliased
from loguru import logger

from ..models.episode import Episode, EpisodeEmbedding
from ..models.core_memory import CoreEmbedding, CoreMemory
from ..models.working_memory import WorkingEmbedding, WorkingMemory
from ..config import settings


class FactCleanupService:
    @staticmethod
    async def clear_duplicate_facts(
        session: AsyncSession, 
        user_id: int, 
        similarity_threshold: float | None = None,
        recent_hours: int = 24
    ) -> int:
        """
        Identify and remove duplicate facts for a given user using in-DB vector comparison.
        Uses pgvector operators to avoid CPU blocking.
        
        Optimized to check only recent episodes (last 24h by default) against the full database
        to avoid O(N²) complexity on large datasets.
        
        Args:
            session: Database session
            user_id: User ID
            similarity_threshold: Cosine similarity threshold (default from config)
            recent_hours: Only check episodes created in last N hours for self-deduplication
        """

        # Determine threshold (distance = 1 - similarity)
        if similarity_threshold is None:
            similarity_threshold = float(getattr(settings, "FACT_CLEANUP_SIMILARITY_THRESHOLD", 0.95))
        
        distance_threshold = 1.0 - similarity_threshold
        to_delete_ids: set[int] = set()

        # 1. Fetch Core Embedding
        core_res = await session.execute(
            select(CoreEmbedding.embedding)
            .join(CoreMemory, CoreMemory.id == CoreEmbedding.core_memory_id)
            .where(CoreMemory.user_id == user_id)
        )
        core_emb = core_res.scalar_one_or_none()

        # 2. Fetch Working Embedding
        work_res = await session.execute(
            select(WorkingEmbedding.embedding)
            .join(WorkingMemory, WorkingMemory.id == WorkingEmbedding.working_memory_id)
            .where(WorkingMemory.user_id == user_id)
        )
        work_emb = work_res.scalar_one_or_none()

        # Helper to normalize numpy/tuples to list if necessary
        def to_list(vec: Any) -> List[float] | None:
            if vec is None: return None
            if hasattr(vec, 'tolist'): return vec.tolist()
            if hasattr(vec, '__iter__') and not isinstance(vec, (list, str, bytes)): return list(vec)
            return vec

        core_emb_list = to_list(core_emb)
        work_emb_list = to_list(work_emb)

        # 3. Identify episodes close to Core Memory
        if core_emb_list is not None:
            stmt_core = (
                select(Episode.id)
                .join(EpisodeEmbedding, Episode.id == EpisodeEmbedding.episode_id)
                .where(
                    and_(
                        Episode.user_id == user_id,
                        EpisodeEmbedding.embedding.cosine_distance(core_emb_list) <= distance_threshold
                    )
                )
            )
            res_core = await session.execute(stmt_core)
            to_delete_ids.update(res_core.scalars().all())

        # 4. Identify episodes close to Working Memory
        if work_emb_list is not None:
            stmt_work = (
                select(Episode.id)
                .join(EpisodeEmbedding, Episode.id == EpisodeEmbedding.episode_id)
                .where(
                    and_(
                        Episode.user_id == user_id,
                        EpisodeEmbedding.embedding.cosine_distance(work_emb_list) <= distance_threshold
                    )
                )
            )
            res_work = await session.execute(stmt_work)
            to_delete_ids.update(res_work.scalars().all())

        # 5. Self-Deduplication (OPTIMIZED: Only check recent episodes)
        # Only check episodes created in the last N hours against all episodes
        # This reduces complexity from O(N²) to O(N*M) where M << N
        
        recent_cutoff = datetime.now(timezone.utc) - timedelta(hours=recent_hours)
        
        OldEp = aliased(Episode)
        OldEmb = aliased(EpisodeEmbedding)
        NewEp = aliased(Episode)
        NewEmb = aliased(EpisodeEmbedding)

        stmt_self = (
            select(OldEp.id)
            .join(OldEmb, OldEp.id == OldEmb.episode_id)
            .where(
                and_(
                    OldEp.user_id == user_id,
                    # OPTIMIZATION: Only check recent episodes as candidates for deletion
                    OldEp.created_at >= recent_cutoff,
                    exists(
                        select(NewEp.id)
                        .join(NewEmb, NewEp.id == NewEmb.episode_id)
                        .where(
                            and_(
                                NewEp.user_id == user_id,
                                NewEp.id != OldEp.id,
                                # Distance check
                                NewEmb.embedding.cosine_distance(OldEmb.embedding) <= distance_threshold,
                                # NewEp is "better" if it's newer, OR same time but higher ID (tie-breaker)
                                or_(
                                    NewEp.created_at > OldEp.created_at,
                                    and_(
                                        NewEp.created_at == OldEp.created_at,
                                        NewEp.id > OldEp.id
                                    )
                                )
                            )
                        )
                    )
                )
            )
        )

        res_self = await session.execute(stmt_self)
        to_delete_ids.update(res_self.scalars().all())

        # 6. Bulk Delete
        if not to_delete_ids:
            logger.debug("No duplicate episodes found for user {}", user_id)
            return 0

        # Delete in chunks if massive (safe approach)
        ids_list = list(to_delete_ids)
        try:
            # Delete embeddings first (FK constraint usually requires this unless cascade is set)
            await session.execute(delete(EpisodeEmbedding).where(EpisodeEmbedding.episode_id.in_(ids_list)))
            # Delete episodes
            await session.execute(delete(Episode).where(Episode.id.in_(ids_list)))
            
            await session.flush()
            
            count = len(ids_list)
            logger.info("Deleted {} duplicate episode(s) for user {} (checked last {}h)", count, user_id, recent_hours)
            return count
            
        except Exception as e:
            logger.exception("Failed to delete duplicate episodes for user {}: {}", user_id, e)
            return 0