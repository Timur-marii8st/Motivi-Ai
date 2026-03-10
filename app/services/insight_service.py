"""Motivi Knows Insight Cards — periodic pattern observations.

Generates 2-3 insight messages per week at semi-random times,
creating variable-ratio reinforcement (Skinner) and curiosity gaps.
"""
from __future__ import annotations

import random
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import func
from sqlmodel import select

from app.config import settings
from app.db import AsyncSessionLocal
from app.models.core_memory import CoreFact, CoreMemory
from app.models.episode import Episode
from app.models.users import User
from app.services.proactive_flows import ProactiveFlows


class InsightService:
    """Schedules and generates 'Motivi Knows' insight cards."""

    @staticmethod
    def schedule_insight_jobs(user_id: int, user_timezone: str | None = None) -> None:
        """Schedule 2-3 insight delivery jobs per week with jittered timing."""
        if not settings.is_feature_enabled("F013_INSIGHT_CARDS"):
            return

        from app.scheduler.scheduler_instance import scheduler

        # Pick 2-3 random weekdays (0=Mon..6=Sun)
        num_days = random.choice([2, 3])
        days = sorted(random.sample(range(7), num_days))
        # Map to APScheduler day_of_week string
        day_names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

        for day_idx in days:
            # Random hour between 10-19 (user-friendly)
            hour = random.randint(10, 19)
            minute = random.randint(0, 59)
            day_name = day_names[day_idx]
            job_id = f"insight_{user_id}_{day_name}"

            existing = scheduler.get_job(job_id)
            if existing:
                scheduler.remove_job(job_id)

            tz_str = user_timezone or "UTC"
            scheduler.add_job(
                func="app.scheduler.jobs:insight_job",
                trigger="cron",
                day_of_week=day_name,
                hour=hour,
                minute=minute,
                timezone=tz_str,
                id=job_id,
                args=[user_id],
                replace_existing=True,
            )
            logger.info(
                "Scheduled insight job for user {} on {} at {}:{} (tz={})",
                user_id,
                day_name,
                hour,
                minute,
                tz_str,
            )

    @staticmethod
    async def generate_insight(user_id: int) -> None:
        """Generate and send a pattern-based insight to the user."""
        if not settings.is_feature_enabled("F013_INSIGHT_CARDS"):
            return

        session = AsyncSessionLocal()
        try:
            # Check break mode
            from app.scheduler.jobs import _is_break_mode_active

            if await _is_break_mode_active(session, user_id):
                logger.info("User {} in break mode; skipping insight", user_id)
                return

            user = await session.get(User, user_id)
            if not user:
                return

            # Gather data for insight generation
            cm_result = await session.execute(
                select(CoreMemory.id).where(CoreMemory.user_id == user_id)
            )
            cm_id = cm_result.scalar_one_or_none()

            facts_text = ""
            if cm_id:
                facts_result = await session.execute(
                    select(CoreFact.fact_text)
                    .where(CoreFact.core_memory_id == cm_id)
                    .limit(20)
                )
                facts = [r[0] for r in facts_result.all()]
                if facts:
                    facts_text = "\n".join(f"- {f}" for f in facts)

            # Recent episodes (last 14 days)
            from datetime import timedelta

            cutoff = datetime.now(timezone.utc) - timedelta(days=14)
            ep_result = await session.execute(
                select(Episode.text)
                .where(
                    Episode.user_id == user_id,
                    Episode.created_at >= cutoff,
                )
                .order_by(Episode.created_at.desc())
                .limit(10)
            )
            episodes = [r[0] for r in ep_result.all()]
            episodes_text = "\n".join(f"- {e[:200]}" for e in episodes) if episodes else ""

            if not facts_text and not episodes_text:
                logger.info("Not enough data for insight for user {}", user_id)
                return

            prompt = (
                "Analyze these facts and recent episodes about me. "
                "Find ONE interesting pattern, trend, or observation. "
                "Be specific with data if possible. Examples:\n"
                "- 'You're most productive on Tuesdays — your habit completion rate is higher'\n"
                "- 'You've mentioned stress about deadlines 3 times recently'\n"
                "- 'You seem to focus on learning new skills in the evenings'\n"
                "Keep it to 2-3 sentences. Be warm and insightful.\n\n"
                f"<UserFacts>\n{facts_text}\n</UserFacts>\n\n"
                f"<RecentEpisodes>\n{episodes_text}\n</RecentEpisodes>"
            )

            flows = ProactiveFlows(session)
            await flows._run_flow(
                user=user,
                prompt=prompt,
                greeting="💡 <b>Motivi Knows</b>",
                top_k=3,
            )
            await session.commit()
            logger.info("Sent insight card to user {}", user_id)

        except Exception:
            logger.exception("Failed to generate insight for user {}", user_id)
            await session.rollback()
        finally:
            await session.close()
