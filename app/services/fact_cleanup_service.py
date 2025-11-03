from __future__ import annotations

from typing import List, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, select, and_
from loguru import logger
import math

from ..models.episode import Episode, EpisodeEmbedding
from ..models.core_memory import CoreEmbedding, CoreMemory
from ..models.working_memory import WorkingEmbedding, WorkingMemory
from ..config import settings


class FactCleanupService:
    @staticmethod
    async def clear_duplicate_facts(session: AsyncSession, user_id: int, similarity_threshold: float | None = None) -> int:
        """
        Identify and remove duplicate facts for a given user using dot-product (cosine similarity on
        L2-normalized vectors). The algorithm keeps the newest episode in a group of near-duplicates
        and deletes older episodes. Episodes that are near-duplicates of the single-row core or
        working memories are also removed.

        Args:
            session (AsyncSession): The database session.
            user_id (int): The ID of the user whose duplicate facts are to be cleared.
            similarity_threshold (float): Cosine similarity threshold in [0, 1] above which two
                embeddings are considered duplicates. Defaults to 0.95.

        Returns:
            int: Number of episode rows deleted.

        Notes:
        - This implementation fetches embeddings into Python and performs an O(n^2) greedy
          de-duplication. It's efficient for typical per-user episode counts (tens to low hundreds).
        - We do not delete `core_memory` or `working_memory` rows; we only remove episode rows
          that duplicate them, preserving the user's canonical short-/long-term memory rows.
        """

        # determine threshold from settings if not provided
        if similarity_threshold is None:
            similarity_threshold = float(getattr(settings, "FACT_CLEANUP_SIMILARITY_THRESHOLD", 0.95))

        # Helper functions
        def l2_norm(vec: List[float]) -> float:
            return math.sqrt(sum(x * x for x in vec))

        def normalize(vec: List[float]) -> List[float]:
            n = l2_norm(vec)
            if n == 0:
                return vec
            return [x / n for x in vec]

        def cosine_similarity(a: List[float], b: List[float]) -> float:
            # assumes vectors are same length and normalized or will normalize here
            # normalize to be safe
            na = normalize(a)
            nb = normalize(b)
            return sum(x * y for x, y in zip(na, nb))

        # 1) Fetch episode embeddings for user (id, created_at, embedding)
        stmt = (
            select(Episode.id, Episode.created_at, EpisodeEmbedding.embedding)
            .join(EpisodeEmbedding, Episode.id == EpisodeEmbedding.episode_id)
            .where(Episode.user_id == user_id)
        )
        result = await session.execute(stmt)
        rows = result.all()  # list of Row tuples
        episodes: List[Tuple[int, object, List[float]]] = []
        for row in rows:
            # row: (id, created_at, embedding)
            ep_id, created_at, embedding = row
            if embedding is None:
                continue
            episodes.append((ep_id, created_at, embedding))

        if len(episodes) <= 1:
            logger.debug("No episodes or a single episode for user {}; nothing to dedupe", user_id)
            return 0

        # 2) Fetch core and working embeddings (one each at most)
        core_emb = None
        result = await session.execute(
            select(CoreEmbedding.embedding)
            .join(CoreMemory, CoreMemory.id == CoreEmbedding.core_memory_id)
            .where(CoreMemory.user_id == user_id)
        )
        core_row = result.scalar_one_or_none()
        if core_row:
            core_emb = core_row

        working_emb = None
        result = await session.execute(
            select(WorkingEmbedding.embedding)
            .join(WorkingMemory, WorkingMemory.id == WorkingEmbedding.working_memory_id)
            .where(WorkingMemory.user_id == user_id)
        )
        working_row = result.scalar_one_or_none()
        if working_row:
            working_emb = working_row

        # 3) Greedy deduplication using pgvector SQL (KNN/distance predicate)
        # sort episodes by created_at desc (keep newest)
        episodes.sort(key=lambda x: x[1], reverse=True)
        to_delete_ids: List[int] = []
        marked = set()

        # distance threshold for cosine_distance (distance = 1 - cosine_similarity)
        distance_threshold = 1.0 - float(similarity_threshold)

        for i, (ep_id_i, created_i, emb_i) in enumerate(episodes):
            if ep_id_i in marked:
                continue

            # 3a) Check similarity to core and working via SQL (fast, uses index)
            if core_emb is not None:
                try:
                    stmt_core = (
                        select(Episode.id)
                        .join(EpisodeEmbedding, Episode.id == EpisodeEmbedding.episode_id)
                        .where(and_(Episode.user_id == user_id, Episode.id == ep_id_i,
                                    EpisodeEmbedding.embedding.cosine_distance(core_emb) <= distance_threshold))
                    )
                    res_core = await session.execute(stmt_core)
                    if res_core.scalar_one_or_none() is not None:
                        logger.info("Episode {} is duplicate of core memory (threshold={}); deleting", ep_id_i, similarity_threshold)
                        to_delete_ids.append(ep_id_i)
                        marked.add(ep_id_i)
                        continue
                except Exception:
                    logger.exception("Failed to compare episode %s to core embedding via SQL", ep_id_i)

            if working_emb is not None:
                try:
                    stmt_work = (
                        select(Episode.id)
                        .join(EpisodeEmbedding, Episode.id == EpisodeEmbedding.episode_id)
                        .where(and_(Episode.user_id == user_id, Episode.id == ep_id_i,
                                    EpisodeEmbedding.embedding.cosine_distance(working_emb) <= distance_threshold))
                    )
                    res_work = await session.execute(stmt_work)
                    if res_work.scalar_one_or_none() is not None:
                        logger.info("Episode {} is duplicate of working memory (threshold={}); deleting", ep_id_i, similarity_threshold)
                        to_delete_ids.append(ep_id_i)
                        marked.add(ep_id_i)
                        continue
                except Exception:
                    logger.exception("Failed to compare episode %s to working embedding via SQL", ep_id_i)

            # 3b) Find other episode neighbors using pgvector distance predicate
            try:
                # find episodes (other than current) whose embedding distance to emb_i is <= distance_threshold
                stmt_neighbors = (
                    select(Episode.id, Episode.created_at)
                    .join(EpisodeEmbedding, Episode.id == EpisodeEmbedding.episode_id)
                    .where(
                        and_(
                            Episode.user_id == user_id,
                            Episode.id != ep_id_i,
                            EpisodeEmbedding.embedding.cosine_distance(emb_i) <= distance_threshold,
                        )
                    )
                )
                res_neighbors = await session.execute(stmt_neighbors)
                neighbors = res_neighbors.all()
                for nb in neighbors:
                    nb_id, nb_created = nb
                    if nb_id in marked:
                        continue
                    # keep the newer (current ep) and delete the older neighbor
                    # if neighbor is newer (rare since we iterate newest-first) then prefer keeping neighbor
                    if nb_created and created_i and nb_created > created_i:
                        # neighbor is newer: mark current for deletion instead
                        logger.debug("Neighbor {} is newer than {}; marking {} for deletion", nb_id, ep_id_i, ep_id_i)
                        to_delete_ids.append(ep_id_i)
                        marked.add(ep_id_i)
                        break
                    else:
                        logger.debug("Marking episode %s as duplicate of %s (SQL neighbor)", nb_id, ep_id_i)
                        to_delete_ids.append(nb_id)
                        marked.add(nb_id)
                # continue outer loop
                if ep_id_i in marked:
                    continue
            except Exception:
                logger.exception("Failed to query neighbors for episode %s via SQL", ep_id_i)

        if not to_delete_ids:
            logger.debug("No duplicate episodes found for user {}", user_id)
            return 0

        # 4) Delete EpisodeEmbedding rows and Episode rows for the flagged ids
        try:
            await session.execute(delete(EpisodeEmbedding).where(EpisodeEmbedding.episode_id.in_(to_delete_ids)))
            await session.execute(delete(Episode).where(Episode.id.in_(to_delete_ids)))
            # rely on outer transaction/handler to commit; flush to ensure DB consistency during request
            await session.flush()
            logger.info("Deleted {} duplicate episode(s) for user {}", len(to_delete_ids), user_id)
            return len(to_delete_ids)
        except Exception as e:
            logger.exception("Failed to delete duplicate episodes for user %s: %s", user_id, e)
            return 0