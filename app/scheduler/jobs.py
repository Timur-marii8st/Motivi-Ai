from __future__ import annotations
from datetime import datetime, timedelta, timezone, date
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, delete

from ..db import AsyncSessionLocal
from ..bot.bot_provider import get_bot_instance
from ..models.users import User
from ..models.habit import Habit, HabitLog
from ..models.settings import UserSettings
from ..models.episode import Episode, EpisodeEmbedding
from ..models.working_memory import WorkingMemory, WorkingEmbedding
from ..services.proactive_flows import ProactiveFlows
from ..models.user_trigger import UserTrigger
from ..config import settings


async def _run_proactive_job(user_id: int, method_name: str) -> None:
    """Generic runner for proactive flow jobs. Handles session lifecycle, break-mode, commit/rollback."""
    logger.info("Running {} for user {}", method_name, user_id)
    session = AsyncSessionLocal()
    try:
        if await _is_break_mode_active(session, user_id):
            logger.info("User {} is in break mode; skipping {}", user_id, method_name)
            return
        user = await session.get(User, user_id)
        if not user:
            logger.warning("User {} not found for {}", user_id, method_name)
            return
        flows = ProactiveFlows(session, bot=get_bot_instance())
        await getattr(flows, method_name)(user)
        await session.commit()
    except Exception as e:
        logger.exception("Error in {} for user {}: {}", method_name, user_id, e)
        await session.rollback()
    finally:
        await session.close()


async def morning_checkin_job(user_id: int):
    """Morning check-in job."""
    await _run_proactive_job(user_id, "morning_checkin")


async def evening_wrapup_job(user_id: int):
    """Evening wrap-up job."""
    await _run_proactive_job(user_id, "evening_wrapup")


async def weekly_plan_job(user_id: int):
    """Weekly plan generation."""
    await _run_proactive_job(user_id, "weekly_plan")


async def monthly_plan_job(user_id: int):
    """Monthly plan generation."""
    await _run_proactive_job(user_id, "monthly_plan")


async def news_digest_job(user_id: int):
    """Personalised news digest delivery (fires after wake_time + offset)."""
    await _run_proactive_job(user_id, "news_digest")


async def custom_trigger_job(user_id: int, trigger_id: int):
    """Execute a user-defined custom proactive trigger."""
    logger.info("Running custom trigger {} for user {}", trigger_id, user_id)
    session = AsyncSessionLocal()
    try:
        if await _is_break_mode_active(session, user_id):
            logger.info("User {} is in break mode; skipping trigger {}", user_id, trigger_id)
            return
        user = await session.get(User, user_id)
        if not user:
            logger.warning("User {} not found for trigger {}", user_id, trigger_id)
            return
        trigger = await session.get(UserTrigger, trigger_id)
        if not trigger or not trigger.active:
            logger.info("Trigger {} is inactive or missing; skipping", trigger_id)
            return
        flows = ProactiveFlows(session, bot=get_bot_instance())
        await flows._run_flow(user=user, prompt=trigger.prompt, greeting=f"⏰ <b>{trigger.name}</b>")
        await session.commit()
    except Exception as e:
        logger.exception("Error in custom trigger {} for user {}: {}", trigger_id, user_id, e)
        await session.rollback()
    finally:
        await session.close()


async def send_one_off_reminder_job(user_id: int, chat_id: int, message_text: str):
    """Send a one-off reminder message to the user (scheduled by LLM tool)."""
    logger.info("Running one-off reminder for user {}", user_id)
    session = AsyncSessionLocal()
    try:
        if await _is_break_mode_active(session, user_id):
            logger.info("User {} is in break mode; skipping one-off reminder", user_id)
            return
        user = await session.get(User, user_id)
        if not user:
            logger.warning("User {} not found for one-off reminder", user_id)
            return
        bot = get_bot_instance()
        await bot.send_message(chat_id, message_text)
        logger.info("Sent one-off reminder to user {} in chat {}", user_id, chat_id)
    except Exception as e:
        logger.exception("Error in send_one_off_reminder_job for user {}: {}", user_id, e)
        await session.rollback()
    finally:
        await session.close()


async def _is_break_mode_active(session: AsyncSession, user_id: int) -> bool:
    """Check if user is in break mode."""
    result = await session.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    user_settings = result.scalar_one_or_none()
    if not user_settings or not user_settings.break_mode_active:
        return False
    now = datetime.now(timezone.utc)
    if user_settings.break_mode_until and user_settings.break_mode_until > now:
        return True
    if user_settings.break_mode_until and user_settings.break_mode_until <= now:
        user_settings.break_mode_active = False
        user_settings.break_mode_until = None
        session.add(user_settings)
        await session.commit()
        return False
    return user_settings.break_mode_active


async def habit_reminder_job(habit_id: int):
    """Send habit reminder."""
    logger.info("Running habit reminder for habit {}", habit_id)
    session = AsyncSessionLocal()
    try:
        habit = await session.get(Habit, habit_id)
        if not habit or not habit.active:
            return
        result = await session.execute(
            select(HabitLog).where(
                HabitLog.habit_id == habit_id,
                HabitLog.log_date == date.today(),
            )
        )
        if result.scalar_one_or_none():
            logger.info("Habit {} already logged today; skipping reminder", habit_id)
            return
        user = await session.get(User, habit.user_id)
        if not user:
            return
        bot = get_bot_instance()
        message = (
            f"\u23f0 Habit Reminder: <b>{habit.name}</b>\n\n"
            f"Don't forget! Current streak: {habit.current_streak} \U0001f525\n"
            f"Reply with /log_habit {habit.id} to mark as done."
        )
        await bot.send_message(user.tg_chat_id, message)
        logger.info("Sent habit reminder for habit {} to user {}", habit_id, user.id)
    except Exception as e:
        logger.exception("Error in habit_reminder_job for habit {}: {}", habit_id, e)
        await session.rollback()
    finally:
        await session.close()


async def cleanup_expired_memories_job():
    """Cleanup episodes older than EPISODE_LIFETIME_DAYS and clear stale working memory."""
    logger.info("Running cleanup_expired_memories_job")
    session = AsyncSessionLocal()
    BATCH_SIZE = 1000
    try:
        life_days = float(settings.EPISODE_LIFETIME_DAYS)
        cutoff = datetime.now(timezone.utc) - timedelta(days=life_days)
        total_deleted = 0
        while True:
            result = await session.execute(
                select(Episode.id).where(Episode.created_at < cutoff).limit(BATCH_SIZE)
            )
            expired_ids = [r for (r,) in result.all()]
            if not expired_ids:
                break
            await session.execute(delete(EpisodeEmbedding).where(EpisodeEmbedding.episode_id.in_(expired_ids)))
            await session.execute(delete(Episode).where(Episode.id.in_(expired_ids)))
            await session.commit()
            total_deleted += len(expired_ids)
            logger.info("Deleted batch of {} expired episodes (total: {})", len(expired_ids), total_deleted)
            if len(expired_ids) < BATCH_SIZE:
                break
        if total_deleted > 0:
            logger.info("Cleanup complete: deleted {} expired episodes total", total_deleted)
        else:
            logger.info("No expired episodes to delete")

        result = await session.execute(
            select(WorkingMemory.id, WorkingMemory.user_id).where(
                WorkingMemory.decay_date != None,
                WorkingMemory.decay_date <= datetime.now(timezone.utc).date()
            )
        )
        stale_wm = result.all()
        if stale_wm:
            stale_wm_ids = [wm_id for wm_id, _ in stale_wm]
            await session.execute(delete(WorkingEmbedding).where(WorkingEmbedding.working_memory_id.in_(stale_wm_ids)))
            from sqlalchemy import update
            await session.execute(
                update(WorkingMemory).where(WorkingMemory.id.in_(stale_wm_ids))
                .values(working_memory_text=None, decay_date=None)
            )
            await session.commit()
            logger.info("Cleared {} stale working memories (preserved records)", len(stale_wm_ids))
        else:
            logger.info("No stale working memories found")
    except Exception as e:
        logger.exception("Error during cleanup_expired_memories_job: {}", e)
        await session.rollback()
    finally:
        await session.close()


async def memory_reveal_job(user_id: int, day: int):
    """Run progressive memory reveal (day 3 or day 7)."""
    logger.info("Running memory reveal day {} for user {}", day, user_id)
    try:
        from ..services.memory_reveal_service import MemoryRevealService
        await MemoryRevealService.run_memory_reveal(user_id, day)
    except Exception as e:
        logger.exception("Error in memory_reveal_job for user {}: {}", user_id, e)


async def insight_job(user_id: int):
    """Generate and send a Motivi Knows insight card."""
    logger.info("Running insight job for user {}", user_id)
    try:
        from ..services.insight_service import InsightService
        await InsightService.generate_insight(user_id)
    except Exception as e:
        logger.exception("Error in insight_job for user {}: {}", user_id, e)


async def premium_taste_job(user_id: int):
    """Send premium feature taste conversion prompt on trial day 5."""
    logger.info("Running premium taste job for user {}", user_id)
    try:
        from ..services.premium_taste_service import PremiumTasteService
        await PremiumTasteService.send_premium_taste(user_id)
    except Exception as e:
        logger.exception("Error in premium_taste_job for user {}: {}", user_id, e)


async def memory_decay_warning_job():
    """Check for decaying working memories and send gentle notifications."""
    from ..config import settings as app_settings
    if not app_settings.is_feature_enabled("F028_MEMORY_DECAY_WARNING"):
        return
    logger.info("Running memory decay warning job")
    session = AsyncSessionLocal()
    try:
        warning_cutoff = (datetime.now(timezone.utc) + timedelta(days=2)).date()
        today = datetime.now(timezone.utc).date()
        result = await session.execute(
            select(WorkingMemory).where(
                WorkingMemory.decay_date != None,
                WorkingMemory.decay_date <= warning_cutoff,
                WorkingMemory.decay_date > today,
                WorkingMemory.working_memory_text != None,
            )
        )
        entries = result.scalars().all()
        warned_users = set()
        for entry in entries:
            if entry.user_id in warned_users:
                continue
            if await _is_break_mode_active(session, entry.user_id):
                continue
            user = await session.get(User, entry.user_id)
            if not user:
                continue
            bot = Bot(token=settings.TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
            try:
                await bot.send_message(
                    user.tg_chat_id,
                    "🧠 Some of your recent context is fading from my working memory. "
                    "Chat with me today to keep it fresh!"
                )
            finally:
                await bot.session.close()
            warned_users.add(entry.user_id)
            logger.info("Sent memory decay warning to user {}", entry.user_id)
    except Exception as e:
        logger.exception("Error in memory_decay_warning_job: {}", e)
    finally:
        await session.close()


async def archive_raw_conversations_job():
    """Archive raw conversation history from Redis to Episodes."""
    logger.info("Running archive_raw_conversations_job")
    session = AsyncSessionLocal()
    try:
        from ..services.conversation_history_service import ConversationHistoryService
        from ..services.episodic_memory_service import EpisodicMemoryService
        from ..embeddings.gemini_embedding_client import GeminiEmbeddings

        redis = ConversationHistoryService._get_redis_client()
        archived_count = 0
        async for key in redis.scan_iter(match="conversation_history:*", count=100):
            try:
                chat_id = int(key.split(":")[-1])
                result = await session.execute(select(User).where(User.tg_chat_id == chat_id))
                user = result.scalar_one_or_none()
                if not user:
                    continue
                history = await ConversationHistoryService.get_history(chat_id)
                if not history or len(history) < 3:
                    continue
                conversation_text = "\n".join([
                    f"{msg['role'].upper()}: {msg['content']}"
                    for msg in history if msg.get('content')
                ])
                today = datetime.now(timezone.utc).date()
                result = await session.execute(
                    select(Episode).where(
                        Episode.user_id == user.id,
                        Episode.created_at >= datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc),
                        Episode.text.like("%Daily Chat Archive%")
                    )
                )
                if result.scalar_one_or_none():
                    continue
                archive_text = (
                    f"Daily Chat Archive ({today.isoformat()}):\n\n{conversation_text}\n\n"
                    "[This is an automatic archive of raw conversation history]"
                )
                episodic_service = EpisodicMemoryService(GeminiEmbeddings())
                await episodic_service.store_episode(session=session, user_id=user.id, fact_text=archive_text)
                archived_count += 1
                logger.info("Archived conversation for user {} (chat_id: {})", user.id, chat_id)
            except Exception as e:
                logger.exception("Error archiving conversation for key {}: {}", key, e)
                continue
        await session.commit()
        logger.info("Archived {} conversations total", archived_count)
    except Exception as e:
        logger.exception("Error during archive_raw_conversations_job: {}", e)
        await session.rollback()
    finally:
        await session.close()
