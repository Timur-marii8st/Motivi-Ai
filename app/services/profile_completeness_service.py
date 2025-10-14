from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from datetime import datetime
from loguru import logger

from ..models.profile_completeness import ProfileCompleteness
from ..models.users import User
from ..models.core_memory import CoreMemory

class ProfileCompletenessService:
    """
    Calculate and update profile completeness score.
    """

    @staticmethod
    async def get_or_create(session: AsyncSession, user_id: int) -> ProfileCompleteness:
        result = await session.execute(
            select(ProfileCompleteness).where(ProfileCompleteness.user_id == user_id)
        )
        pc = result.scalar_one_or_none()
        if not pc:
            pc = ProfileCompleteness(user_id=user_id)
            session.add(pc)
            await session.flush()
        return pc

    @staticmethod
    async def calculate_score(session: AsyncSession, user_id: int) -> float:
        """
        Calculate completeness score based on filled fields.
        """
        user = await session.get(User, user_id)
        if not user:
            return 0.0
        
        core_result = await session.execute(
            select(CoreMemory).where(CoreMemory.user_id == user_id)
        )
        core = core_result.scalar_one_or_none()
        
        # Weight different fields
        score = 0.0
        total_weight = 0.0
        
        fields = [
            (user.name, 10),
            (user.age, 5),
            (user.timezone, 10),
            (user.wake_time, 8),
            (user.bed_time, 8),
            (user.occupation_json, 15),
        ]
        
        if core:
            fields.extend([
                (core.goals_json, 20),
                (core.sleep_schedule_json, 5),
            ])
        
        for field_value, weight in fields:
            total_weight += weight
            if field_value:
                if isinstance(field_value, dict) and field_value:
                    score += weight
                elif field_value:
                    score += weight
        
        final_score = score / total_weight if total_weight > 0 else 0.0
        logger.debug("Profile completeness for user {}: {:.2f}", user_id, final_score)
        return final_score

    @staticmethod
    async def update_score(session: AsyncSession, user_id: int):
        """
        Recalculate and update score.
        """
        pc = await ProfileCompletenessService.get_or_create(session, user_id)
        new_score = await ProfileCompletenessService.calculate_score(session, user_id)
        
        pc.score = new_score
        pc.last_profile_update = datetime.utcnow()
        pc.touch()
        session.add(pc)
        await session.flush()
        
        logger.info("Updated completeness score for user {} to {:.2f}", user_id, new_score)

    @staticmethod
    async def decay_question_frequency(session: AsyncSession, user_id: int, decay_factor: float = 0.95):
        """
        Gradually reduce question frequency as profile matures.
        """
        pc = await ProfileCompletenessService.get_or_create(session, user_id)
        
        # Decay based on score: higher score = faster decay
        if pc.score > 0.7:
            pc.question_frequency *= decay_factor
            pc.question_frequency = max(0.1, pc.question_frequency)  # Floor at 10%
            pc.touch()
            session.add(pc)
            await session.flush()

    @staticmethod
    async def increment_question_count(session: AsyncSession, user_id: int):
        """Track that Moti asked a question."""
        pc = await ProfileCompletenessService.get_or_create(session, user_id)
        pc.total_questions_asked += 1
        pc.touch()
        session.add(pc)
        await session.flush()

    @staticmethod
    async def increment_interaction_count(session: AsyncSession, user_id: int):
        """Track user interaction."""
        pc = await ProfileCompletenessService.get_or_create(session, user_id)
        pc.total_interactions += 1
        pc.touch()
        session.add(pc)
        await session.flush()