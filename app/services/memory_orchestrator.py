from __future__ import annotations
from typing import Dict, Any, List, Optional
import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from loguru import logger

from ..models.users import User
from ..models.core_memory import CoreMemory
from ..models.working_memory import WorkingMemory, WorkingMemoryEntry
from ..models.episode import Episode
from .core_memory_service import CoreMemoryService
from .working_memory_service import WorkingMemoryService
from .episodic_memory_service import EpisodicMemoryService

class MemoryPack:
    """Container for assembled memory context."""
    def __init__(
        self,
        user: User,
        core: CoreMemory,
        core_facts: Optional[List] ,
        working: WorkingMemory,
        episodes: List[Episode],
        working_history: Optional[List[WorkingMemory]] = None,
    ):
        self.user = user
        self.core = core
        self.working = working
        self.episodes = episodes
        # outside of the async DB context which triggers MissingGreenlet
        self.working_history = working_history or []
        # List of CoreFact objects (may be empty)
        self.core_facts = core_facts or []

    def to_context_dict(self) -> Dict[str, Any]:
        """Serialize for LLM prompt injection."""
        return {
            "user_profile": {
                "name": self.user.name,
                "age": self.user.age,
                "timezone": self.user.user_timezone,
                "wake_time": self.user.wake_time.isoformat() if self.user.wake_time else None,
                "bed_time": self.user.bed_time.isoformat() if self.user.bed_time else None,
                "occupation": self.user.occupation_json,
            },
                "core_memory": {
                "sleep_schedule": self.core.sleep_schedule_json,
                # Provide a list of core facts each with their created_at so LLMs receive structured facts
                "core_facts": [
                    {"fact": cf.fact_text, "created_at": cf.created_at.isoformat() if cf.created_at else None}
                    for cf in self.core_facts
                ],
                # Keep the overall created_at for backward compatibility (when this record was created)
                "created_at": self.core.created_at.isoformat() if self.core.created_at else None,
            },
            "working_memory": {
                "current": self.working.working_memory_text,
                "created_at": self.working.created_at.isoformat() if self.working.created_at else None,
                "history": [
                    {
                        "text": w.working_memory_text,
                        "order": w.history_order,
                        "created_at": w.created_at.isoformat() if w.created_at else None,
                    }
                    for w in sorted(self.working_history, key=lambda x: x.history_order or 999)
                ],
                "stale": self.working.decay_date and self.working.decay_date < datetime.now().date(),
            },
            "relevant_episodes": [
                {
                    "text": ep.text,
                    "created_at": ep.created_at.isoformat(),
                }
                for ep in self.episodes
            ],
        }

from datetime import datetime

class MemoryOrchestrator:
    """
    Assembles full memory context (Core + Working + Episodic) for a given user and query.
    """

    def __init__(self, episodic_service: EpisodicMemoryService, core_service: CoreMemoryService, working_service: WorkingMemoryService):
        self.episodic_service = episodic_service
        self.core_service = core_service
        self.working_service = working_service

    async def assemble(
        self, session: AsyncSession, user: User, query_text: str, top_k: int = 5
    ) -> MemoryPack:
        """
        Fetch Core, Working, and semantically similar Episodic memories.
        """
        # Retrieve similar CoreFact entries (per-fact retrieval)
        similar_core_facts = await self.core_service.retrieve_similar(
            session, user.id, query_text=query_text
        )
        # Ensure CoreMemory row exists
        core = await self.core_service.get_or_create(session, user.id)
        # List all core facts for the user (for full context)
        core_facts = await self.core_service.list_facts_for_user(session, user.id)

        working_results = await self.working_service.retrieve_similar(
            session, user.id, query_text=query_text
        )
        # Get all working memory entries for this user
        working_history_result = await session.execute(
            select(WorkingMemoryEntry)
            .where(WorkingMemoryEntry.user_id == user.id)
            .order_by(WorkingMemoryEntry.history_order.asc())
            .limit(7)
        )
        working_history = working_history_result.scalars().all()

        # Choose current working memory summary (from semantic results or ensure it exists)
        if working_results:
            working = working_results[0]
        else:
            working = await self.working_service.get_or_create(session, user.id)
            
        # RAG retrieval
        episodes = await self.episodic_service.retrieve_similar(
            session, user.id, query_text=query_text
        )

        logger.debug(
            "Assembled memory pack for user {}: {} episodes retrieved", user.id, len(episodes)
        )

        return MemoryPack(
            user=user,
            core=core,
            core_facts=core_facts,
            working=working,
            episodes=episodes,
            working_history=working_history,
        )