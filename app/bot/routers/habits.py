from __future__ import annotations
from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from datetime import date
from loguru import logger
from ..states import HabitCreation


from ...services.profile_services import get_or_create_user
from ...services.habit_service import HabitService
from ...scheduler.job_manager import JobManager
import html

router = Router(name="habits")

@router.message(F.text == "/habits")
async def list_habits_cmd(message: Message, session):
    """List all active habits."""
    user = await get_or_create_user(session, message.from_user.id, message.chat.id)
    habits = await HabitService.list_habits(session, user.id, active_only=True)
    
    if not habits:
        await message.answer("You don't have any habits yet. Use /add_habit to create one!")
        return
    
    text = "<b>📋 Your Active Habits:</b>\n\n"
    for h in habits:
        stats = await HabitService.get_habit_stats(session, h.id)
        text += (
            f"🔹 <b>{h.name}</b> (ID: {h.id})\n"
            f"   Streak: {stats['current_streak']} 🔥 | Best: {stats['longest_streak']}\n"
            f"   Cadence: {h.cadence} | Target: {h.target_count}\n"
            f"   Reminder: {h.reminder_time or 'None'}\n\n"
        )
    
    await message.answer(text)

@router.message(F.text.startswith("/add_habit"))
async def add_habit_cmd(message: Message, state: FSMContext):
    """Start habit creation flow."""
    await message.answer("What's the name of your new habit?")
    await state.set_state("HabitCreation:name")

@router.message(HabitCreation.name, F.text)
async def habit_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await message.answer("Great! How often? Reply: daily or weekly")
    await state.set_state("HabitCreation:cadence")

@router.message(HabitCreation.cadence, F.text)
async def habit_cadence(message: Message, state: FSMContext):
    cadence = message.text.strip().lower()
    if cadence not in ["daily", "weekly"]:
        await message.answer("Please choose 'daily' or 'weekly'.")
        return
    
    await state.update_data(cadence=cadence)
    await message.answer("Do you want a daily reminder? Reply with time (HH:MM) or 'no'.")
    await state.set_state("HabitCreation:reminder")

@router.message(HabitCreation.reminder, F.text)
async def habit_reminder(message: Message, state: FSMContext, session):
    text = message.text.strip().lower()
    reminder_time = None
    
    if text != "no":
        from ...utils.timeparse import parse_hhmm
        reminder_time = parse_hhmm(text)
        if not reminder_time:
            await message.answer("Invalid time format. Use HH:MM or 'no'.")
            return
    
    data = await state.get_data()
    user = await get_or_create_user(session, message.from_user.id, message.chat.id)
    
    habit = await HabitService.create_habit(
        session,
        user.id,
        name=data["name"],
        cadence=data["cadence"],
        reminder_time=reminder_time.isoformat() if reminder_time else None,
    )
    await session.commit()
    
    # Schedule reminder
    if reminder_time:
        await JobManager.schedule_habit_reminders(session, user.id)
    
    await message.answer(f"✅ Habit <b>{habit.name}</b> created! Use /log_habit {habit.id} to log it.")
    await state.clear()

@router.message(F.text.regexp(r"^/log_habit\s+(\d+)"))
async def log_habit_cmd(message: Message, session):
    """Log a habit completion."""
    import re
    match = re.match(r"^/log_habit\s+(\d+)", message.text)
    if not match:
        await message.answer("Usage: /log_habit <habit_id>")
        return
    
    habit_id = int(match.group(1))
    user = await get_or_create_user(session, message.from_user.id, message.chat.id)
    
    try:
        log = await HabitService.log_habit(session, habit_id, date.today())
        await session.commit()
        
        habit = await session.get(Habit, habit_id)
        await message.answer(
            f"✅ Logged <b>{habit.name}</b>!\n"
            f"Current streak: {habit.current_streak} 🔥"
        )
    except ValueError as e:
        await message.answer(f"❌ {html.escape(str(e))}")
    except Exception as e:
        logger.exception("Failed to log habit: {}", e)
        await message.answer("Failed to log habit. Please try again.")

from ...models.habit import Habit