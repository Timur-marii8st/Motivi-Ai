"""Memory milestone celebrations.

Fires celebratory messages when users cross memory count thresholds,
making invisible investment visible (Endowed Progress Effect).
"""
from __future__ import annotations

import random
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties

from app.config import settings
from app.models.core_memory import CoreFact, CoreMemory
from app.models.episode import Episode
from app.models.users import User
from app.services.event_bus import event_bus
from app.services.gamification.schemas import (
    GameEvent,
    GameEventType,
    MEMORY_MILESTONES,
)


class MilestoneService:
    """Checks and celebrates memory milestones."""

    @staticmethod
    async def check_memory_milestone(
        session: AsyncSession,
        user: User,
        chat_id: int,
    ) -> None:
        """Check if user has crossed a memory milestone and celebrate.

        Queries total CoreFact + Episode counts and sends a message
        when a new milestone threshold is crossed.
        """
        if not settings.is_feature_enabled("F007_MEMORY_MILESTONES"):
            return

        try:
            # Count core facts
            cm_result = await session.execute(
                select(CoreMemory.id).where(CoreMemory.user_id == user.id)
            )
            cm = cm_result.scalar_one_or_none()
            fact_count = 0
            if cm:
                fact_result = await session.execute(
                    select(func.count())
                    .select_from(CoreFact)
                    .where(CoreFact.core_memory_id == cm)
                )
                fact_count = fact_result.scalar_one()

            # Count episodes
            ep_result = await session.execute(
                select(func.count())
                .select_from(Episode)
                .where(Episode.user_id == user.id)
            )
            episode_count = ep_result.scalar_one()

            total = fact_count + episode_count

            # Find the highest milestone crossed that hasn't been celebrated
            new_milestone = None
            for m in MEMORY_MILESTONES:
                if user.last_memory_milestone < m <= total:
                    new_milestone = m

            if new_milestone is None:
                return

            # Sample 3 random facts for the celebration message
            sample_facts = []
            if cm and fact_count > 0:
                facts_result = await session.execute(
                    select(CoreFact.fact_text)
                    .where(CoreFact.core_memory_id == cm)
                    .order_by(func.random())
                    .limit(3)
                )
                sample_facts = [row[0] for row in facts_result.all()]

            # Build celebration message
            facts_text = ""
            if sample_facts:
                facts_preview = " and ".join(
                    f'"{f[:60]}"' for f in sample_facts[:2]
                )
                facts_text = f" — like the fact that {facts_preview}"

            message = (
                f"🎉 <b>Memory Milestone!</b>\n\n"
                f"I now know <b>{total}</b> things about you{facts_text}.\n\n"
                f"We've built something meaningful together. "
                f"Every conversation makes me understand you better."
            )

            bot = Bot(
                token=settings.TELEGRAM_BOT_TOKEN,
                default=DefaultBotProperties(parse_mode="HTML"),
            )
            try:
                await bot.send_message(chat_id, message)
            finally:
                await bot.session.close()

            # Update milestone marker
            user.last_memory_milestone = new_milestone
            user.touch()
            session.add(user)

            logger.info(
                "User {} crossed memory milestone {} (total: {})",
                user.id,
                new_milestone,
                total,
            )

            await event_bus.emit(
                GameEvent(
                    event=GameEventType.MEMORY_MILESTONE,
                    user_id=user.id,
                    feature_id="F007",
                    properties={
                        "milestone": new_milestone,
                        "total": total,
                        "facts": fact_count,
                        "episodes": episode_count,
                    },
                    timestamp=datetime.now(timezone.utc),
                )
            )

        except Exception:
            logger.exception(
                "Error checking memory milestone for user {}", user.id
            )
