from __future__ import annotations
import re
import html
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from loguru import logger

from ...models.habit import Habit
from ...services.profile_services import get_or_create_user
from ...services.habit_service import HabitService
from ...scheduler.job_manager import JobManager
from ..states import HabitCreation

router = Router(name="habits")


@router.message(F.text == "/cancel")
async def cancel_habit_creation(message: Message, state: FSMContext):
    """Cancel habit creation process."""
    current_state = await state.get_state()
    if current_state is None or not current_state.startswith("HabitCreation"):
        return
    await state.clear()
    await message.answer("\u274c \u0421\u043e\u0437\u0434\u0430\u043d\u0438\u0435 \u043f\u0440\u0438\u0432\u044b\u0447\u043a\u0438 \u043e\u0442\u043c\u0435\u043d\u0435\u043d\u043e.")


@router.message(F.text == "/habits")
async def list_habits_cmd(message: Message, session):
    """List all active habits."""
    user = await get_or_create_user(session, message.from_user.id, message.chat.id)
    habits = await HabitService.list_habits(session, user.id, active_only=True)

    if not habits:
        await message.answer("\u0423 \u0442\u0435\u0431\u044f \u0435\u0449\u0451 \u043d\u0435\u0442 \u043f\u0440\u0438\u0432\u044b\u0447\u0435\u043a. \u041d\u0430\u0436\u043c\u0438 /add_habit, \u0447\u0442\u043e\u0431\u044b \u0441\u043e\u0437\u0434\u0430\u0442\u044c!")
        return

    # Batch: habit model already carries streak data; no extra per-habit query needed
    text = "<b>\U0001f4cb \u0422\u0432\u043e\u0438 \u0430\u043a\u0442\u0438\u0432\u043d\u044b\u0435 \u043f\u0440\u0438\u0432\u044b\u0447\u043a\u0438:</b>\n\n"
    for h in habits:
        stats = await HabitService.get_habit_stats(session, h.id)
        text += (
            f"\U0001f539 <b>{html.escape(h.name)}</b> (ID: {h.id})\n"
            f"   Streak: {stats['current_streak']} \U0001f525 | Best: {stats['longest_streak']}\n"
            f"   Cadence: {h.cadence} | Target: {h.target_count}\n"
            f"   Reminder: {h.reminder_time or 'None'}\n\n"
        )

    await message.answer(text)


@router.message(F.text.startswith("/add_habit"))
async def add_habit_cmd(message: Message, state: FSMContext):
    """Start habit creation flow."""
    await state.clear()
    await message.answer("\u041a\u0430\u043a \u0437\u043e\u0432\u0443\u0442 \u0442\u0432\u043e\u044e \u043d\u043e\u0432\u0443\u044e \u043f\u0440\u0438\u0432\u044b\u0447\u043a\u0443?")
    await state.set_state(HabitCreation.name)


@router.message(HabitCreation.name, F.text)
async def habit_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await message.answer("\u041e\u0442\u043b\u0438\u0447\u043d\u043e! \u041a\u0430\u043a \u0447\u0430\u0441\u0442\u043e? \u0415\u0436\u0435\u0434\u043d\u0435\u0432\u043d\u043e \u0438\u043b\u0438 \u0435\u0436\u0435\u043d\u0435\u0434\u0435\u043b\u044c\u043d\u043e")
    await state.set_state(HabitCreation.cadence)


@router.message(HabitCreation.cadence, F.text)
async def habit_cadence(message: Message, state: FSMContext):
    cadence = message.text.strip().lower()
    if cadence not in ["\u0435\u0436\u0435\u0434\u043d\u0435\u0432\u043d\u043e", "\u0435\u0436\u0435\u043d\u0435\u0434\u0435\u043b\u044c\u043d\u043e", "daily", "weekly"]:
        await message.answer("\u041f\u043e\u0436\u0430\u043b\u0443\u0439\u0441\u0442\u0430, \u0432\u044b\u0431\u0435\u0440\u0438 '\u0435\u0436\u0435\u0434\u043d\u0435\u0432\u043d\u043e' \u0438\u043b\u0438 '\u0435\u0436\u0435\u043d\u0435\u0434\u0435\u043b\u044c\u043d\u043e'.")
        return
    cadence = "daily" if cadence in ["\u0435\u0436\u0435\u0434\u043d\u0435\u0432\u043d\u043e", "daily"] else "weekly"
    await state.update_data(cadence=cadence)
    await message.answer("\u0425\u043e\u0447\u0435\u0448\u044c \u0431\u0443\u0434\u0443 \u0435\u0436\u0435\u0434\u043d\u0435\u0432\u043d\u043e \u043d\u0430\u043f\u043e\u043c\u0438\u043d\u0430\u0442\u044c? \u041e\u0442\u0432\u0435\u0442\u044c \u0432\u0440\u0435\u043c\u0435\u043d\u0435\u043c (\u0427\u0427:\u041c\u041c) \u0438\u043b\u0438 '\u043d\u0435\u0442'.")
    await state.set_state(HabitCreation.reminder)


@router.message(HabitCreation.reminder, F.text)
async def habit_reminder(message: Message, state: FSMContext, session):
    text = message.text.strip().lower()
    reminder_time = None

    if text not in ["no", "\u043d\u0435\u0442"]:
        from ...utils.timeparse import parse_hhmm
        reminder_time = parse_hhmm(text)
        if not reminder_time:
            await message.answer("\u041d\u0435\u0432\u0435\u0440\u043d\u044b\u0439 \u0444\u043e\u0440\u043c\u0430\u0442 \u0432\u0440\u0435\u043c\u0435\u043d\u0438. \u041e\u0442\u0432\u0435\u0442\u044c \u0427\u0427:\u041c\u041c \u0438\u043b\u0438 '\u043d\u0435\u0442'.")
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

    if reminder_time:
        await JobManager.schedule_habit_reminders(session, user.id)

    await message.answer(f"\u2705 \u041f\u0440\u0438\u0432\u044b\u0447\u043a\u0430 <b>{html.escape(habit.name)}</b> \u0441\u043e\u0437\u0434\u0430\u043d\u0430! \u041d\u0430\u0436\u043c\u0438 /log_habit {habit.id}, \u0447\u0442\u043e\u0431\u044b \u0437\u0430\u0444\u0438\u043a\u0441\u0438\u0440\u043e\u0432\u0430\u0442\u044c \u0435\u0451.")
    await state.clear()


@router.message(F.text.regexp(r"^/log_habit\s+(\d+)"))
async def log_habit_cmd(message: Message, session):
    """Log a habit completion."""
    match = re.match(r"^/log_habit\s+(\d+)", message.text)
    if not match:
        await message.answer("\u0418\u0441\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u043d\u0438\u0435: /log_habit <id_\u043f\u043e\u0432\u0435\u0434\u0435\u043d\u0438\u044f>")
        return

    habit_id = int(match.group(1))
    user = await get_or_create_user(session, message.from_user.id, message.chat.id)

    try:
        # Use user_timezone (correct property name) with fallback to UTC
        tz = ZoneInfo(user.user_timezone) if user.user_timezone else timezone.utc
        log_date = datetime.now(timezone.utc).astimezone(tz).date()
        log = await HabitService.log_habit(session, habit_id, log_date)
        await session.commit()

        habit = await session.get(Habit, habit_id)
        if habit:
            await message.answer(
                f"\u2705 \u0417\u0430\u0444\u0438\u043a\u0441\u0438\u0440\u043e\u0432\u0430\u043d\u043e <b>{html.escape(habit.name)}</b>!\n"
                f"\u0422\u0435\u043a\u0443\u0449\u0438\u0439 \u0441\u0442\u0440\u0438\u043a: {habit.current_streak} \U0001f525"
            )
    except ValueError as e:
        await message.answer(f"\u274c {html.escape(str(e))}")
    except Exception as e:
        logger.exception("Failed to log habit {}: {}", habit_id, e)
        await message.answer("\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0437\u0430\u0444\u0438\u043a\u0441\u0438\u0440\u043e\u0432\u0430\u0442\u044c \u043f\u0440\u0438\u0432\u044b\u0447\u043a\u0443. \u041f\u043e\u043f\u0440\u043e\u0431\u0443\u0439 \u0435\u0449\u0451 \u0440\u0430\u0437.")
