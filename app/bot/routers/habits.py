from __future__ import annotations
import re
import html
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from loguru import logger

from ...models.habit import Habit
from ...services.profile_services import get_or_create_user
from ...services.habit_service import HabitService
from ...scheduler.job_manager import JobManager
from ..states import HabitCreation

router = Router(name="habits")


def _habit_keyboard(habit_id: int) -> InlineKeyboardMarkup:
    """Build inline keyboard for a single habit card."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Отметить", callback_data=f"log_habit:{habit_id}"),
        InlineKeyboardButton(text="🗑 Архив", callback_data=f"archive_habit:{habit_id}"),
    ]])


@router.message(F.text == "/cancel")
async def cancel_habit_creation(message: Message, state: FSMContext):
    """Cancel habit creation process."""
    current_state = await state.get_state()
    if current_state is None or not current_state.startswith("HabitCreation"):
        return
    await state.clear()
    await message.answer("❌ Создание привычки отменено.")


@router.message(F.text == "/habits")
async def list_habits_cmd(message: Message, session):
    """List all active habits with inline action buttons."""
    user = await get_or_create_user(session, message.from_user.id, message.chat.id)
    habits = await HabitService.list_habits(session, user.id, active_only=True)

    if not habits:
        await message.answer("У тебя ещё нет привычек. Нажми /add_habit, чтобы создать!")
        return

    await message.answer("<b>📋 Твои активные привычки:</b>")

    for h in habits:
        stats = await HabitService.get_habit_stats(session, h.id)
        card = (
            f"🔹 <b>{html.escape(h.name)}</b>\n"
            f"   Streak: {stats['current_streak']} 🔥 | Best: {stats['longest_streak']}\n"
            f"   Cadence: {h.cadence} | Target: {h.target_count}\n"
            f"   Reminder: {h.reminder_time or 'None'}\n"
        )
        await message.answer(card, reply_markup=_habit_keyboard(h.id))


@router.callback_query(F.data.startswith("log_habit:"))
async def log_habit_callback(callback: CallbackQuery, session):
    """Log habit completion via inline button."""
    habit_id = int(callback.data.split(":")[1])
    user = await get_or_create_user(session, callback.from_user.id, callback.message.chat.id)

    try:
        tz = ZoneInfo(user.user_timezone) if user.user_timezone else timezone.utc
        log_date = datetime.now(timezone.utc).astimezone(tz).date()
        await HabitService.log_habit(session, habit_id, log_date)
        await session.commit()

        habit = await session.get(Habit, habit_id)
        if habit:
            stats = await HabitService.get_habit_stats(session, habit.id)
            updated_card = (
                f"🔹 <b>{html.escape(habit.name)}</b> ✅\n"
                f"   Streak: {stats['current_streak']} 🔥 | Best: {stats['longest_streak']}\n"
                f"   Cadence: {habit.cadence} | Target: {habit.target_count}\n"
                f"   Reminder: {habit.reminder_time or 'None'}\n"
            )
            await callback.answer(f"✅ Зафиксировано! Streak: {stats['current_streak']} 🔥")
            await callback.message.edit_text(updated_card, reply_markup=_habit_keyboard(habit_id))
    except ValueError as e:
        await callback.answer(f"❌ {str(e)}", show_alert=True)
    except Exception as e:
        logger.exception("Failed to log habit {} via callback: {}", habit_id, e)
        await callback.answer("Не удалось зафиксировать привычку. Попробуй ещё раз.", show_alert=True)


@router.callback_query(F.data.startswith("archive_habit:"))
async def archive_habit_callback(callback: CallbackQuery, session):
    """Archive habit via inline button."""
    habit_id = int(callback.data.split(":")[1])
    user = await get_or_create_user(session, callback.from_user.id, callback.message.chat.id)

    habit = await session.get(Habit, habit_id)
    if not habit or habit.user_id != user.id:
        await callback.answer("Привычка не найдена.", show_alert=True)
        return

    await HabitService.archive_habit(session, habit_id)
    await session.commit()

    await callback.answer("🗑 Привычка архивирована.")
    await callback.message.edit_text(
        f"🗑 <b>{html.escape(habit.name)}</b> — <i>архивирована</i>",
        reply_markup=None,
    )


@router.message(F.text.startswith("/add_habit"))
async def add_habit_cmd(message: Message, state: FSMContext):
    """Start habit creation flow."""
    await state.clear()
    await message.answer("Как назовём новую привычку?")
    await state.set_state(HabitCreation.name)


@router.message(HabitCreation.name, F.text)
async def habit_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await message.answer("Отлично! Как часто? Ежедневно или еженедельно")
    await state.set_state(HabitCreation.cadence)


@router.message(HabitCreation.cadence, F.text)
async def habit_cadence(message: Message, state: FSMContext):
    cadence = message.text.strip().lower()
    if cadence not in ["ежедневно", "еженедельно", "daily", "weekly"]:
        await message.answer("Пожалуйста, выбери 'ежедневно' или 'еженедельно'.")
        return
    cadence = "daily" if cadence in ["ежедневно", "daily"] else "weekly"
    await state.update_data(cadence=cadence)
    await message.answer("Хочешь буду ежедневно напоминать? Ответь временем (ЧЧ:ММ) или 'нет'.")
    await state.set_state(HabitCreation.reminder)


@router.message(HabitCreation.reminder, F.text)
async def habit_reminder(message: Message, state: FSMContext, session):
    text = message.text.strip().lower()
    reminder_time = None

    if text not in ["no", "нет"]:
        from ...utils.timeparse import parse_hhmm
        reminder_time = parse_hhmm(text)
        if not reminder_time:
            await message.answer("Неверный формат времени. Ответь ЧЧ:ММ или 'нет'.")
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

    await message.answer(
        f"✅ Привычка <b>{html.escape(habit.name)}</b> создана!\n"
        f"Используй /habits, чтобы отмечать выполнение кнопками."
    )
    await state.clear()


@router.message(F.text.regexp(r"^/log_habit\s+(\d+)"))
async def log_habit_cmd(message: Message, session):
    """Log a habit completion via text command (kept for compatibility with reminders)."""
    match = re.match(r"^/log_habit\s+(\d+)", message.text)
    if not match:
        await message.answer("Использование: /log_habit <id_повеления>")
        return

    habit_id = int(match.group(1))
    user = await get_or_create_user(session, message.from_user.id, message.chat.id)

    try:
        tz = ZoneInfo(user.user_timezone) if user.user_timezone else timezone.utc
        log_date = datetime.now(timezone.utc).astimezone(tz).date()
        await HabitService.log_habit(session, habit_id, log_date)
        await session.commit()

        habit = await session.get(Habit, habit_id)
        if habit:
            await message.answer(
                f"✅ Зафиксировано <b>{html.escape(habit.name)}</b>!\n"
                f"Текущий streak: {habit.current_streak} 🔥"
            )
    except ValueError as e:
        await message.answer(f"❌ {html.escape(str(e))}")
    except Exception as e:
        logger.exception("Failed to log habit {}: {}", habit_id, e)
        await message.answer("Не удалось зафиксировать привычку. Попробуй ещё раз.")
