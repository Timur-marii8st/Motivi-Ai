from typing import Dict, Any
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlmodel import select, delete
from loguru import logger

from ..models.users import User
from ..models.core_memory import CoreMemory
from ..models.working_memory import WorkingMemory
from ..models.episode import Episode, EpisodeEmbedding
from ..models.task import Task
from ..models.settings import UserSettings
from ..models.habit import Habit, HabitLog
from ..models.oauth_token import OAuthToken
from ..models.profile_completeness import ProfileCompleteness
from ..scheduler.job_manager import JobManager

class AccountService:
    """
    Manage user account lifecycle: export, delete.
    """

    @staticmethod
    async def export_user_data(session: AsyncSession, user_id: int) -> Dict[str, Any]:
        """
        GDPR-compliant data export using an efficient, eager-loaded query.
        """
        # A single query to fetch the user and all related data
        query = (
            select(User)
            .where(User.id == user_id)
            .options(
                selectinload(User.core_memory),
                selectinload(User.working_memory),
                selectinload(User.episodes),
                selectinload(User.tasks),
                selectinload(User.habits),
                selectinload(User.settings),
                selectinload(User.profile_completeness),
            )
        )
        result = await session.execute(query)
        user = result.scalar_one_or_none()

        if not user:
            return {}

        # Access related data directly from the user object's relationships
        core = user.core_memory
        working = user.working_memory
        settings = user.settings
        pc = user.profile_completeness
        
        export = {
            "export_date": datetime.utcnow().isoformat(),
            "user": {
                "id": user.id,
                "name": user.name,
                "age": user.age,
                "timezone": user.timezone,
                "wake_time": user.wake_time.isoformat() if user.wake_time else None,
                "bed_time": user.bed_time.isoformat() if user.bed_time else None,
                "occupation": user.occupation_json,
                "created_at": user.created_at.isoformat(),
            },
            "core_memory": {
                "goals": core.goals_json if core else None,
                "sleep_schedule": core.sleep_schedule_json if core else None,
            },
            "working_memory": {
                "focus_summary": working.focus_summary if working else None,
                "short_term_goals": working.short_term_goals_json if working else None,
            },
            "episodes": [
                {
                    "type": ep.type,
                    "text": ep.text,
                    "metadata": ep.metadata_json,
                    "created_at": ep.created_at.isoformat(),
                }
                for ep in user.episodes
            ],
            "tasks": [
                {
                    "title": t.title,
                    "description": t.description,
                    "status": t.status,
                    "due_dt": t.due_dt.isoformat() if t.due_dt else None,
                    "created_at": t.created_at.isoformat(),
                }
                for t in user.tasks
            ],
            "habits": [
                {
                    "name": h.name,
                    "description": h.description,
                    "cadence": h.cadence,
                    "current_streak": h.current_streak,
                    "longest_streak": h.longest_streak,
                    "created_at": h.created_at.isoformat(),
                }
                for h in user.habits
            ],
            "settings": {
                "break_mode_active": settings.break_mode_active if settings else False,
                "enable_morning_checkin": settings.enable_morning_checkin if settings else True,
                "enable_evening_wrapup": settings.enable_evening_wrapup if settings else True,
            } if settings else {},
            "profile_completeness": {
                "score": pc.score if pc else 0.0,
                "total_interactions": pc.total_interactions if pc else 0,
            } if pc else {},
        }
        
        logger.info("Exported data for user {}", user_id)
        return export

    @staticmethod
    async def delete_user_account(session: AsyncSession, user_id: int):
        """
        Permanently delete user and all associated data.
        """
        JobManager.remove_user_jobs(user_id)
        
        await session.execute(delete(EpisodeEmbedding).where(
            EpisodeEmbedding.episode_id.in_(
                select(Episode.id).where(Episode.user_id == user_id)
            )
        ))
        await session.execute(delete(Episode).where(Episode.user_id == user_id))
        await session.execute(delete(HabitLog).where(
            HabitLog.habit_id.in_(
                select(Habit.id).where(Habit.user_id == user_id)
            )
        ))
        await session.execute(delete(Habit).where(Habit.user_id == user_id))
        await session.execute(delete(Task).where(Task.user_id == user_id))
        await session.execute(delete(OAuthToken).where(OAuthToken.user_id == user_id))
        await session.execute(delete(UserSettings).where(UserSettings.user_id == user_id))
        await session.execute(delete(WorkingMemory).where(WorkingMemory.user_id == user_id))
        await session.execute(delete(CoreMemory).where(CoreMemory.user_id == user_id))
        await session.execute(delete(ProfileCompleteness).where(ProfileCompleteness.user_id == user_id))
        await session.execute(delete(User).where(User.id == user_id))
        
        logger.warning("Deleted all data for user {}", user_id)