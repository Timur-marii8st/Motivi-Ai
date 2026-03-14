from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, List

from loguru import logger
from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models.core_memory import CoreEmbedding, CoreMemory
from ..models.episode import Episode, EpisodeEmbedding
from ..models.working_memory import WorkingEmbedding, WorkingMemory


def _to_list(vec: Any) -> List[float] | None:
    if vec is None:
        return None
    if hasattr(vec, "tolist"):
        return vec.tolist()
    if hasattr(vec, "__iter__") and not isinstance(vec, (list, str, bytes)):
        return list(vec)
    return vec


def _cosine_distance(vec_a: Any, vec_b: Any) -> float:
    a = _to_list(vec_a)
    b = _to_list(vec_b)
    if a is None or b is None or len(a) != len(b):
        return 1.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        fx = float(x)
        fy = float(y)
        dot += fx * fy
        norm_a += fx * fx
        norm_b += fy * fy
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 1.0
    similarity = dot / ((norm_a ** 0.5) * (norm_b ** 0.5))
    return 1.0 - similarity


class FactCleanupService:
    @staticmethod
    async def clear_duplicate_facts(
        session: AsyncSession,
        user_id: int,
        similarity_threshold: float | None = None,
        recent_hours: int = 24,
    ) -> int:
        """
        Identify and remove duplicate episodes for a user.

        Steps:
        1. Remove episodes close to current core/working embeddings via indexed search.
        2. Self-deduplicate in Python for only recent episodes against all user episodes.
           This avoids a heavy SQL self-join with vector distance in JOIN predicates.
        """
        if similarity_threshold is None:
            similarity_threshold = float(
                getattr(settings, "FACT_CLEANUP_SIMILARITY_THRESHOLD", 0.95)
            )

        distance_threshold = 1.0 - similarity_threshold
        to_delete_ids: set[int] = set()

        core_res = await session.execute(
            select(CoreEmbedding.embedding)
            .join(CoreMemory, CoreMemory.id == CoreEmbedding.core_memory_id)
            .where(CoreMemory.user_id == user_id)
        )
        core_emb = core_res.scalar_one_or_none()

        work_res = await session.execute(
            select(WorkingEmbedding.embedding)
            .join(WorkingMemory, WorkingMemory.id == WorkingEmbedding.working_memory_id)
            .where(WorkingMemory.user_id == user_id)
        )
        work_emb = work_res.scalar_one_or_none()

        core_emb_list = _to_list(core_emb)
        work_emb_list = _to_list(work_emb)

        if core_emb_list is not None:
            stmt_core = (
                select(Episode.id)
                .join(EpisodeEmbedding, Episode.id == EpisodeEmbedding.episode_id)
                .where(
                    and_(
                        Episode.user_id == user_id,
                        EpisodeEmbedding.embedding.cosine_distance(core_emb_list)
                        <= distance_threshold,
                    )
                )
            )
            res_core = await session.execute(stmt_core)
            to_delete_ids.update(res_core.scalars().all())

        if work_emb_list is not None:
            stmt_work = (
                select(Episode.id)
                .join(EpisodeEmbedding, Episode.id == EpisodeEmbedding.episode_id)
                .where(
                    and_(
                        Episode.user_id == user_id,
                        EpisodeEmbedding.embedding.cosine_distance(work_emb_list)
                        <= distance_threshold,
                    )
                )
            )
            res_work = await session.execute(stmt_work)
            to_delete_ids.update(res_work.scalars().all())

        recent_cutoff = datetime.now(timezone.utc) - timedelta(hours=recent_hours)
        recent_rows_res = await session.execute(
            select(Episode.id, Episode.created_at, EpisodeEmbedding.embedding)
            .join(EpisodeEmbedding, Episode.id == EpisodeEmbedding.episode_id)
            .where(Episode.user_id == user_id, Episode.created_at >= recent_cutoff)
        )
        recent_rows = recent_rows_res.all()

        if recent_rows:
            all_rows_res = await session.execute(
                select(Episode.id, Episode.created_at, EpisodeEmbedding.embedding)
                .join(EpisodeEmbedding, Episode.id == EpisodeEmbedding.episode_id)
                .where(Episode.user_id == user_id)
            )
            all_rows = all_rows_res.all()

            for old_id, old_created_at, old_embedding in recent_rows:
                for new_id, new_created_at, new_embedding in all_rows:
                    if new_id == old_id:
                        continue
                    is_better = new_created_at > old_created_at or (
                        new_created_at == old_created_at and new_id > old_id
                    )
                    if not is_better:
                        continue
                    if _cosine_distance(old_embedding, new_embedding) <= distance_threshold:
                        to_delete_ids.add(old_id)
                        break

        if not to_delete_ids:
            logger.debug("No duplicate episodes found for user {}", user_id)
            return 0

        ids_list = list(to_delete_ids)
        try:
            await session.execute(
                delete(EpisodeEmbedding).where(EpisodeEmbedding.episode_id.in_(ids_list))
            )
            await session.execute(delete(Episode).where(Episode.id.in_(ids_list)))
            await session.flush()
            count = len(ids_list)
            logger.info(
                "Deleted {} duplicate episode(s) for user {} (checked last {}h)",
                count,
                user_id,
                recent_hours,
            )
            return count
        except Exception as e:
            logger.exception("Failed to delete duplicate episodes for user {}: {}", user_id, e)
            return 0
