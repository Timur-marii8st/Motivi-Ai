"""Progressive Memory Reveal — day 3 and day 7 proactive messages.

Shows users what Motivi has learned, making invisible investment visible
and inviting corrections to improve accuracy.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import func
from sqlmodel import select

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties

from app.config import settings
from app.db import AsyncSessionLocal
from app.models.core_memory import CoreFact, CoreMemory
from app.models.users import User
from app.services.event_bus import event_bus
from app.services.gamification.schemas import GameEvent, GameEventType


class MemoryRevealService:
    """Schedules and runs memory reveal messages at day 3 and day 7."""

    @staticmethod
    def schedule_memory_reveals(user_id: int, created_at: datetime) -> None:
        """Schedule APScheduler jobs for day 3 and day 7 reveals."""
        if not settings.is_feature_enabled("F009_MEMORY_REVEAL"):
            return

        from app.scheduler.scheduler_instance import scheduler
        from apscheduler.triggers.date import DateTrigger
        from pytz import utc as _utc

        for day in (3, 7):
            run_at = created_at + timedelta(days=day)
            # Don't schedule in the past
            if run_at <= datetime.now(timezone.utc):
                continue

            job_id = f"memory_reveal_{day}_{user_id}"
            if scheduler.get_job(job_id):
                scheduler.remove_job(job_id)

            scheduler.add_job(
                func="app.scheduler.jobs:memory_reveal_job",
                trigger=DateTrigger(run_date=run_at, timezone=_utc),
                id=job_id,
                args=[user_id, day],
                replace_existing=True,
            )
            logger.info(
                "Scheduled memory reveal day {} for user {} at {}",
                day,
                user_id,
                run_at,
            )

    @staticmethod
    async def run_memory_reveal(user_id: int, day: int) -> None:
        """Execute the memory reveal for the given day (3 or 7)."""
        if not settings.is_feature_enabled("F009_MEMORY_REVEAL"):
            return

        session = AsyncSessionLocal()
        try:
            user = await session.get(User, user_id)
            if not user:
                logger.warning("User {} not found for memory reveal", user_id)
                return

            # Check break mode
            from app.models.settings import UserSettings

            us_result = await session.execute(
                select(UserSettings).where(UserSettings.user_id == user_id)
            )
            us = us_result.scalar_one_or_none()
            if us and us.break_mode_active:
                logger.info(
                    "User {} in break mode; skipping memory reveal", user_id
                )
                return

            # Count and sample facts
            cm_result = await session.execute(
                select(CoreMemory.id).where(CoreMemory.user_id == user_id)
            )
            cm_id = cm_result.scalar_one_or_none()

            fact_count = 0
            sample_facts: list[str] = []
            if cm_id:
                count_result = await session.execute(
                    select(func.count())
                    .select_from(CoreFact)
                    .where(CoreFact.core_memory_id == cm_id)
                )
                fact_count = count_result.scalar_one()

                facts_result = await session.execute(
                    select(CoreFact.fact_text)
                    .where(CoreFact.core_memory_id == cm_id)
                    .order_by(func.random())
                    .limit(3)
                )
                sample_facts = [row[0] for row in facts_result.all()]

            if fact_count == 0:
                logger.info(
                    "User {} has no facts yet; skipping day {} reveal",
                    user_id,
                    day,
                )
                return

            # Build message based on day
            if day == 3:
                facts_list = "\n".join(
                    f"  • {f[:100]}" for f in sample_facts
                )
                message = (
                    f"🧠 <b>I've learned {fact_count} things about you so far!</b>\n\n"
                    f"Here are a few:\n{facts_list}\n\n"
                    f"Want to see more? Keep chatting with me and I'll learn "
                    f"even more about your goals and interests.\n\n"
                    f"If anything is incorrect, just tell me and I'll fix it!"
                )
            else:  # day 7
                facts_list = "\n".join(
                    f"  • {f[:100]}" for f in sample_facts
                )
                message = (
                    f"🧠 <b>I now know {fact_count} things about you!</b>\n\n"
                    f"Here's a sample of what I've learned:\n{facts_list}\n\n"
                    f"Am I getting it right? Tell me if anything needs "
                    f"correcting — you can use /correct to review and edit "
                    f"what I know about you."
                )

            bot = Bot(
                token=settings.TELEGRAM_BOT_TOKEN,
                default=DefaultBotProperties(parse_mode="HTML"),
            )
            try:
                await bot.send_message(user.tg_chat_id, message)
                logger.info(
                    "Sent day {} memory reveal to user {} ({} facts)",
                    day,
                    user_id,
                    fact_count,
                )
            finally:
                await bot.session.close()

        except Exception:
            logger.exception(
                "Error running memory reveal day {} for user {}",
                day,
                user_id,
            )
        finally:
            await session.close()
