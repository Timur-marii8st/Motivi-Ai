"""Premium Feature Taste — trial day 5 conversion prompt.

Sends a targeted message showing actual usage stats and the
impending loss when the trial ends, leveraging Endowment Effect.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from loguru import logger

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.config import settings
from app.db import AsyncSessionLocal
from app.models.users import User


class PremiumTasteService:
    """Schedules and sends trial day-5 conversion prompts."""

    @staticmethod
    def schedule_trial_day5_job(user_id: int, trial_start: datetime) -> None:
        """Schedule the premium taste message for 5 days after trial start."""
        if not settings.is_feature_enabled("F019_PREMIUM_TASTE"):
            return

        from app.scheduler.scheduler_instance import scheduler
        from apscheduler.triggers.date import DateTrigger
        from pytz import utc as _utc

        run_at = trial_start + timedelta(days=5)
        if run_at <= datetime.now(timezone.utc):
            return

        job_id = f"premium_taste_{user_id}"
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)

        scheduler.add_job(
            func="app.scheduler.jobs:premium_taste_job",
            trigger=DateTrigger(run_date=run_at, timezone=_utc),
            id=job_id,
            args=[user_id],
            replace_existing=True,
        )
        logger.info("Scheduled premium taste for user {} at {}", user_id, run_at)

    @staticmethod
    async def send_premium_taste(user_id: int) -> None:
        """Send the conversion prompt with actual usage stats."""
        if not settings.is_feature_enabled("F019_PREMIUM_TASTE"):
            return

        session = AsyncSessionLocal()
        try:
            user = await session.get(User, user_id)
            if not user:
                return

            # Only send to trial users
            if not user.is_trial:
                logger.info(
                    "User {} is no longer in trial; skipping premium taste",
                    user_id,
                )
                return

            # Query usage stats from Redis
            import redis.asyncio as aioredis

            r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            try:
                # Scan for code execution keys
                code_count = 0
                async for key in r.scan_iter(
                    match=f"code_exec:{user_id}:*", count=100
                ):
                    val = await r.get(key)
                    code_count += int(val) if val else 0

                # Scan for search keys
                search_count = 0
                async for key in r.scan_iter(
                    match=f"search:{user_id}:*", count=100
                ):
                    val = await r.get(key)
                    search_count += int(val) if val else 0
            finally:
                await r.aclose()

            if code_count == 0 and search_count == 0:
                logger.info(
                    "User {} has no premium feature usage; skipping taste",
                    user_id,
                )
                return

            # Build message
            parts = []
            if code_count > 0:
                parts.append(f"code execution <b>{code_count}</b> times")
            if search_count > 0:
                parts.append(f"web search <b>{search_count}</b> times")

            usage_text = " and ".join(parts)
            days_left = max(
                0,
                settings.TRIAL_DAYS
                - (datetime.now(timezone.utc) - user.created_at).days,
            )

            message = (
                f"📊 You've used {usage_text} this week.\n\n"
                f"Your trial ends in <b>{days_left}</b> days — after that, "
                f"code execution drops to {settings.CODE_EXEC_DAILY_TRIAL}/day "
                f"and web search to {settings.SEARCH_DAILY_TRIAL}/day.\n\n"
                f"Want to keep the full experience?"
            )

            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="⭐ Subscribe",
                            callback_data="subscribe_prompt",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="No thanks",
                            callback_data="dismiss_premium_taste",
                        )
                    ],
                ]
            )

            bot = Bot(
                token=settings.TELEGRAM_BOT_TOKEN,
                default=DefaultBotProperties(parse_mode="HTML"),
            )
            try:
                await bot.send_message(
                    user.tg_chat_id, message, reply_markup=keyboard
                )
                logger.info("Sent premium taste to user {}", user_id)
            finally:
                await bot.session.close()

        except Exception:
            logger.exception("Failed to send premium taste to user {}", user_id)
        finally:
            await session.close()
