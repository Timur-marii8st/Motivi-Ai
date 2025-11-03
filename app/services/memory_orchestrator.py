from __future__ import annotations
from typing import Dict, Any, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from loguru import logger

from ..models.users import User
from ..models.task import Task
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
        working: WorkingMemory,
        episodes: List[Episode],
        tasks: Optional[List[Task]] = None,
        working_history: Optional[List[WorkingMemory]] = None,
    ):
        self.user = user
        self.core = core
        self.working = working
        self.episodes = episodes
        # outside of the async DB context which triggers MissingGreenlet
        self.tasks = tasks or []
        self.working_history = working_history or []

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
                # tasks is a list of dicts with minimal task info
                "tasks": [
                    {
                        "title": t.title,
                        "status": t.status,
                        "due_dt": t.due_dt.isoformat() if getattr(t, "due_dt", None) else None,
                    }
                    for t in self.tasks
                ],
            },
            "core_memory": {
                "sleep_schedule": self.core.sleep_schedule_json,
                "core_facts": self.core.core_text,
            },
            "working_memory": {
                "current": self.working.working_memory_text,
                "history": [
                    {
                        "text": w.working_memory_text,
                        "order": w.history_order,
                        "updated_at": w.updated_at.isoformat()
                    }
                    for w in sorted(self.working_history, key=lambda x: x.history_order or 999)
                ],
                "stale": self.working.decay_date and self.working.decay_date < datetime.now().date(),
            },
            "relevant_episodes": [
                {
                    "text": ep.text,
                    "date": ep.created_at.isoformat(),
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
        core_results = await self.core_service.retrieve_similar(
            session, user.id, query_text=query_text
        )
        # core_service.retrieve_similar returns a list; we expect a single CoreMemory.
        # Prefer the top hit when present, otherwise ensure a CoreMemory row exists.
        if core_results:
            core = core_results[0]
        else:
            core = await self.core_service.get_or_create(session, user.id)

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

        # Use the most recent working memory or create new if none exists
        if working_history:
            working = working_history[0]  # newest entry (history_order=1)
        else:
            working = await self.working_service.get_or_create(session, user.id)
            working_history = [working]
            
        # RAG retrieval
        episodes = await self.episodic_service.retrieve_similar(
            session, user.id, query_text=query_text
        )

        logger.debug(
            "Assembled memory pack for user {}: {} episodes retrieved", user.id, len(episodes)
        )

        # Eagerly load tasks using the provided async session so we don't
        # trigger a lazy load later outside of the DB context (which causes
        # the MissingGreenlet error).
        tasks_result = await session.execute(select(Task).where(Task.user_id == user.id))
        tasks = tasks_result.scalars().all()

        return MemoryPack(
            user=user,
            core=core,
            working=working,
            episodes=episodes,
            tasks=tasks,
            working_history=working_history
        )