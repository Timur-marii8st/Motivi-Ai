from __future__ import annotations
from datetime import datetime, timezone
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, delete
from aiogram.client.default import DefaultBotProperties 

from ..db import AsyncSessionLocal
from ..models.users import User
from ..models.settings import UserSettings
from ..services.proactive_flows import ProactiveFlows
from ..config import settings
from ..models.episode import Episode, EpisodeEmbedding
from ..models.working_memory import WorkingMemory, WorkingEmbedding
from datetime import timedelta, datetime
from sqlmodel import delete

async def morning_checkin_job(user_id: int):
    """Morning check-in job."""
    logger.info("Running morning check-in for user {}", user_id)
    session = AsyncSessionLocal()
    try:
        # Check break mode
        if await _is_break_mode_active(session, user_id):
            logger.info("User {} is in break mode; skipping morning check-in", user_id)
            return
        
        user = await session.get(User, user_id)
        if not user:
            logger.warning("User {} not found", user_id)
            return
        
        flows = ProactiveFlows(session)
        await flows.morning_checkin(user)
        await session.commit()
    except Exception as e:
        logger.exception("Error in morning_checkin_job for user {}: {}", user_id, e)
        await session.rollback()
    finally:
        await session.close()

async def evening_wrapup_job(user_id: int):
    """Evening wrap-up job."""
    logger.info("Running evening wrap-up for user {}", user_id)
    session = AsyncSessionLocal()
    try:
        if await _is_break_mode_active(session, user_id):
            logger.info("User {} is in break mode; skipping evening wrap-up", user_id)
            return
        
        user = await session.get(User, user_id)
        if not user:
            return
        
        flows = ProactiveFlows(session)
        await flows.evening_wrapup(user)
        await session.commit()
    except Exception as e:
        logger.exception("Error in evening_wrapup_job for user {}: {}", user_id, e)
        await session.rollback()
    finally:
        await session.close()

async def weekly_plan_job(user_id: int):
    """Weekly plan generation."""
    logger.info("Running weekly plan for user {}", user_id)
    session = AsyncSessionLocal()
    try:
        if await _is_break_mode_active(session, user_id):
            logger.info("User {} is in break mode; skipping weekly plan", user_id)
            return
        
        user = await session.get(User, user_id)
        if not user:
            return
        
        flows = ProactiveFlows(session)
        await flows.weekly_plan(user)
        await session.commit()
    except Exception as e:
        logger.exception("Error in weekly_plan_job for user {}: {}", user_id, e)
        await session.rollback()
    finally:
        await session.close()

async def monthly_plan_job(user_id: int):
    """Monthly plan generation."""
    logger.info("Running monthly plan for user {}", user_id)
    session = AsyncSessionLocal()
    try:
        if await _is_break_mode_active(session, user_id):
            logger.info("User {} is in break mode; skipping monthly plan", user_id)
            return
        
        user = await session.get(User, user_id)
        if not user:
            return
        
        flows = ProactiveFlows(session)
        await flows.monthly_plan(user)
        await session.commit()
    except Exception as e:
        logger.exception("Error in monthly_plan_job for user {}: {}", user_id, e)
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

        from aiogram import Bot
        
        bot = Bot(
            token=settings.TELEGRAM_BOT_TOKEN, 
            default=DefaultBotProperties(parse_mode="HTML")
        )
        
        await bot.send_message(chat_id, message_text)
        await bot.session.close() # Good practice to close the session since it's one-off
        logger.info("Sent one-off reminder to user {} in chat {}", user_id, chat_id)
    except Exception as e:
        logger.exception("Error in send_one_off_reminder_job for user {}: {}", user_id, e)
        await session.rollback()
    finally:
        await session.close()

async def _is_break_mode_active(session: AsyncSession, user_id: int) -> bool:
    """Check if user is in break mode."""
    result = await session.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    settings = result.scalar_one_or_none()
    
    if not settings or not settings.break_mode_active:
        return False
    
    if settings.break_mode_until and settings.break_mode_until > datetime.now(timezone.utc):
        return True
    
    # Expired; deactivate
    if settings.break_mode_until and settings.break_mode_until <= datetime.now(timezone.utc):
        settings.break_mode_active = False
        settings.break_mode_until = None
        session.add(settings)
        await session.commit()
        return False
    
    return settings.break_mode_active

async def habit_reminder_job(habit_id: int):
    """Send habit reminder."""
    logger.info("Running habit reminder for habit {}", habit_id)
    session = AsyncSessionLocal()
    try:
        from ..models.habit import Habit
        from aiogram import Bot
        
        habit = await session.get(Habit, habit_id)
        if not habit or not habit.active:
            return
        
        # Check if already logged today
        from ..models.habit import HabitLog
        from datetime import date
        result = await session.execute(
            select(HabitLog).where(
                HabitLog.habit_id == habit_id,
                HabitLog.log_date == date.today(),
            )
        )
        log = result.scalar_one_or_none()
        
        if log:
            logger.info("Habit {} already logged today; skipping reminder", habit_id)
            return
        
        # Get user and send reminder
        from ..models.users import User
        user = await session.get(User, habit.user_id)
        if not user:
            return
        
        bot = Bot(
            token=settings.TELEGRAM_BOT_TOKEN, 
            default=DefaultBotProperties(parse_mode="HTML")
        )
        
        message = (
            f"⏰ Habit Reminder: <b>{habit.name}</b>\n\n"
            f"Don't forget! Current streak: {habit.current_streak} 🔥\n"
            f"Reply with /log_habit {habit.id} to mark as done."
        )
        
        await bot.send_message(user.tg_chat_id, message)
        await bot.session.close() # Close session
        logger.info("Sent habit reminder for habit {} to user {}", habit_id, user.id)
    except Exception as e:
        logger.exception("Error in habit_reminder_job for habit {}: {}", habit_id, e)
        await session.rollback()
    finally:
        await session.close()
        
async def cleanup_expired_memories_job():
    """
    Cleanup episodes older than EPISODE_LIFETIME_DAYS and clear stale working memory.
    Uses batch processing to avoid memory issues with large datasets.
    """
    logger.info("Running cleanup_expired_memories_job")
    session = AsyncSessionLocal()
    BATCH_SIZE = 1000  # Process in batches to avoid OOM
    
    try:
        # Episodes: delete EpisodeEmbedding rows and Episode rows older than lifetime
        life_days = float(settings.EPISODE_LIFETIME_DAYS)
        cutoff = datetime.now(timezone.utc) - timedelta(days=life_days)

        total_deleted = 0
        while True:
            # Fetch batch of expired episode IDs
            result = await session.execute(
                select(Episode.id)
                .where(Episode.created_at < cutoff)
                .limit(BATCH_SIZE)
            )
            expired_ids = [r for (r,) in result.all()]

            if not expired_ids:
                break  # No more expired episodes

            # Delete embeddings and episodes for this batch
            await session.execute(
                delete(EpisodeEmbedding).where(EpisodeEmbedding.episode_id.in_(expired_ids))
            )
            await session.execute(
                delete(Episode).where(Episode.id.in_(expired_ids))
            )
            await session.commit()
            
            total_deleted += len(expired_ids)
            logger.info("Deleted batch of {} expired episodes (total: {})", len(expired_ids), total_deleted)
            
            # If we got fewer than BATCH_SIZE, we're done
            if len(expired_ids) < BATCH_SIZE:
                break

        if total_deleted > 0:
            logger.info("Cleanup complete: deleted {} expired episodes total", total_deleted)
        else:
            logger.info("No expired episodes to delete")

        # Working memory: Clear text for stale working memories instead of deleting the record
        # This preserves the user's working memory structure while resetting the content
        result = await session.execute(
            select(WorkingMemory.id, WorkingMemory.user_id)
            .where(
                WorkingMemory.decay_date != None, 
                WorkingMemory.decay_date <= datetime.now(timezone.utc).date()
            )
        )
        stale_wm = result.all()

        if stale_wm:
            stale_wm_ids = [wm_id for wm_id, _ in stale_wm]
            
            # Delete embeddings
            await session.execute(
                delete(WorkingEmbedding).where(WorkingEmbedding.working_memory_id.in_(stale_wm_ids))
            )
            
            # Clear working memory text instead of deleting the record
            # This allows the user to maintain their working memory structure
            from sqlalchemy import update
            await session.execute(
                update(WorkingMemory)
                .where(WorkingMemory.id.in_(stale_wm_ids))
                .values(
                    working_memory_text=None,
                    decay_date=None
                )
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