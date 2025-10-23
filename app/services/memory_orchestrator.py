from __future__ import annotations
from typing import Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from ..models.users import User
from ..models.core_memory import CoreMemory
from ..models.working_memory import WorkingMemory
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
        working: WorkingMemory,
        episodes: List[Episode],
    ):
        self.user = user
        self.core = core
        self.working = working
        self.episodes = episodes

    def to_context_dict(self) -> Dict[str, Any]:
        """Serialize for LLM prompt injection."""
        return {
            "user_profile": {
                "name": self.user.name,
                "age": self.user.age,
                "timezone": self.user.timezone,
                "wake_time": self.user.wake_time.isoformat() if self.user.wake_time else None,
                "bed_time": self.user.bed_time.isoformat() if self.user.bed_time else None,
                "occupation": self.user.occupation_json,
            },
            "core_memory": {
                "goals": self.core.goals_json,
                "sleep_schedule": self.core.sleep_schedule_json,
                "core_text": self.core.core_text,
            },
            "working_memory": {
                "focus_summary": self.working.focus_summary,
                "short_term_goals": self.working.short_term_goals_json,
                "stale": self.working.decay_date and self.working.decay_date < datetime.now().date(),
            },
            "relevant_episodes": [
                {
                    "type": ep.type,
                    "text": ep.text,
                    "date": ep.created_at.isoformat(),
                    "metadata": ep.metadata_json,
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
        core = await self.core_service.retrieve_similar(
            session, user.id, fact_text=query_text, metadata=None
        )
        working = await self.working_service.retrieve_similar(
            session, user.id, fact_text=query_text, metadata=None
        )
        # RAG retrieval
        episodes = await self.episodic_service.retrieve_similar(
            session, user.id, query_text, top_k=top_k
        )

        logger.debug(
            "Assembled memory pack for user {}: {} episodes retrieved", user.id, len(episodes)
        )
        return MemoryPack(user=user, core=core, working=working, episodes=episodes)