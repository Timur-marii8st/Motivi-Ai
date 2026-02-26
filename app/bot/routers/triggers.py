from __future__ import annotations
import html
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from loguru import logger

from ...services.profile_services import get_or_create_user
from ...services.user_trigger_service import UserTriggerService
from ...utils.timeparse import parse_hhmm
from ..states import TriggerCreation

router = Router(name="triggers")

# Valid APScheduler weekday aliases users can type
_WEEKDAY_MAP = {
    "mon": "mon", "tue": "tue", "wed": "wed", "thu": "thu",
    "fri": "fri", "sat": "sat", "sun": "sun",
    "пн": "mon", "вт": "tue", "ср": "wed", "чт": "thu",
    "пт": "fri", "сб": "sat", "вс": "sun",
    "weekdays": "mon-fri", "weekends": "sat,sun",
    "будни": "mon-fri", "выходные": "sat,sun",
    "daily": None, "ежедневно": None,
}


def _trigger_keyboard(trigger_id: int, active: bool) -> InlineKeyboardMarkup:
    toggle_label = "🔕 Отключить" if active else "🔔 Включить"
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=toggle_label, callback_data=f"toggle_trigger:{trigger_id}"),
        InlineKeyboardButton(text="🗑 Удалить", callback_data=f"del_trigger:{trigger_id}"),
    ]])


def _schedule_label(t: object) -> str:
    """Format a UserTrigger into a human-readable schedule string."""
    time_str = f"{t.cron_hour:02d}:{t.cron_minute:02d}"
    days = t.cron_weekdays or "каждый день"
    return f"{time_str}, {days}"


@router.message(F.text == "/triggers")
async def list_triggers_cmd(message: Message, session):
    """List user's custom triggers with inline action buttons."""
    user = await get_or_create_user(session, message.from_user.id, message.chat.id)
    triggers = await UserTriggerService.list_triggers(session, user.id)

    if not triggers:
        await message.answer(
            "У тебя нет пользовательских триггеров.\n"
            "Нажми /add_trigger, чтобы создать напоминание с произвольным запросом!"
        )
        return

    await message.answer("<b>⏰ Твои триггеры:</b>")
    for t in triggers:
        status = "✅" if t.active else "🔕"
        card = (
            f"{status} <b>{html.escape(t.name)}</b>\n"
            f"   Расписание: {_schedule_label(t)}\n"
            f"   Запрос: <i>{html.escape(t.prompt[:80])}{'…' if len(t.prompt) > 80 else ''}</i>\n"
        )
        await message.answer(card, reply_markup=_trigger_keyboard(t.id, t.active))


@router.callback_query(F.data.startswith("toggle_trigger:"))
async def toggle_trigger_callback(callback: CallbackQuery, session):
    trigger_id = int(callback.data.split(":")[1])
    user = await get_or_create_user(session, callback.from_user.id, callback.message.chat.id)

    trigger = await UserTriggerService.toggle_trigger(session, trigger_id, user.id)
    if not trigger:
        await callback.answer("Триггер не найден.", show_alert=True)
        return

    await session.commit()

    # Reschedule jobs to reflect new active state
    try:
        from ...scheduler.job_manager import JobManager
        await JobManager.schedule_user_triggers(session, user)
    except Exception as e:
        logger.warning("Failed to reschedule triggers after toggle for user {}: {}", user.id, e)

    status = "✅" if trigger.active else "🔕"
    toggle_label = "🔕 Отключить" if trigger.active else "🔔 Включить"
    card = (
        f"{status} <b>{html.escape(trigger.name)}</b>\n"
        f"   Расписание: {_schedule_label(trigger)}\n"
        f"   Запрос: <i>{html.escape(trigger.prompt[:80])}{'…' if len(trigger.prompt) > 80 else ''}</i>\n"
    )
    await callback.answer("Обновлено!")
    await callback.message.edit_text(
        card,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=toggle_label, callback_data=f"toggle_trigger:{trigger_id}"),
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"del_trigger:{trigger_id}"),
        ]])
    )


@router.callback_query(F.data.startswith("del_trigger:"))
async def del_trigger_callback(callback: CallbackQuery, session):
    trigger_id = int(callback.data.split(":")[1])
    user = await get_or_create_user(session, callback.from_user.id, callback.message.chat.id)

    deleted = await UserTriggerService.delete_trigger(session, trigger_id, user.id)
    if not deleted:
        await callback.answer("Триггер не найден.", show_alert=True)
        return

    await session.commit()

    # Remove the APScheduler job
    try:
        from ...scheduler.scheduler_instance import scheduler
        job_id = f"trigger_{user.id}_{trigger_id}"
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
    except Exception as e:
        logger.warning("Failed to remove scheduler job for trigger {}: {}", trigger_id, e)

    await callback.answer("🗑 Триггер удалён.")
    await callback.message.edit_text("🗑 <i>Триггер удалён.</i>", reply_markup=None)


@router.message(F.text == "/cancel")
async def cancel_trigger_creation(message: Message, state: FSMContext):
    """Cancel trigger creation process."""
    current_state = await state.get_state()
    if current_state is None or not current_state.startswith("TriggerCreation"):
        return
    await state.clear()
    await message.answer("❌ Создание триггера отменено.")


@router.message(F.text.startswith("/add_trigger"))
async def add_trigger_cmd(message: Message, state: FSMContext):
    """Start trigger creation flow."""
    await state.clear()
    await message.answer(
        "Создаём новый триггер! Как его назовём? (макс. 50 символов)\n"
        "Например: <i>Вечерний обзор целей</i>\n\n"
        "Отправь /cancel, чтобы отменить."
    )
    await state.set_state(TriggerCreation.name)


@router.message(TriggerCreation.name, F.text)
async def trigger_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) > 50:
        await message.answer("Имя слишком длинное (макс. 50 символов). Попробуй ещё раз.")
        return
    await state.update_data(name=name)
    await message.answer(
        "Отлично! Теперь введи запрос для Мотиви — что она должна сделать, когда сработает триггер.\n"
        "Например: <i>Напомни мне проверить прогресс по целям недели и предложи 3 приоритета на завтра.</i>"
    )
    await state.set_state(TriggerCreation.prompt)


@router.message(TriggerCreation.prompt, F.text)
async def trigger_prompt(message: Message, state: FSMContext):
    prompt = message.text.strip()
    if len(prompt) > 500:
        await message.answer("Запрос слишком длинный (макс. 500 символов). Сократи его.")
        return
    await state.update_data(prompt=prompt)
    await message.answer(
        "В какое время срабатывать? Введи время в формате ЧЧ:ММ (в твоём часовом поясе).\n"
        "Например: <code>20:00</code>"
    )
    await state.set_state(TriggerCreation.schedule)


@router.message(TriggerCreation.schedule, F.text)
async def trigger_schedule(message: Message, state: FSMContext):
    t = parse_hhmm(message.text.strip())
    if t is None:
        await message.answer("Неверный формат. Введи время в формате ЧЧ:ММ, например <code>20:00</code>.")
        return
    await state.update_data(cron_hour=t.hour, cron_minute=t.minute)
    await message.answer(
        "Как часто срабатывать?\n\n"
        "• <code>ежедневно</code> — каждый день\n"
        "• <code>будни</code> — пн–пт\n"
        "• <code>выходные</code> — сб–вс\n"
        "• Или перечисли дни: <code>пн,ср,пт</code> / <code>mon,wed,fri</code>"
    )
    await state.set_state(TriggerCreation.weekdays)


@router.message(TriggerCreation.weekdays, F.text)
async def trigger_weekdays(message: Message, state: FSMContext, session):
    raw = message.text.strip().lower()

    # Parse weekdays input
    cron_weekdays: str | None = None
    if raw in _WEEKDAY_MAP:
        cron_weekdays = _WEEKDAY_MAP[raw]
    else:
        # Try comma-separated individual day tokens
        parts = [p.strip() for p in raw.replace(" ", "").split(",")]
        resolved = [_WEEKDAY_MAP[p] for p in parts if p in _WEEKDAY_MAP and _WEEKDAY_MAP[p]]
        if not resolved or len(resolved) != len(parts):
            await message.answer(
                "Не удалось распознать дни. Попробуй: <code>ежедневно</code>, <code>будни</code>, "
                "или перечисли дни через запятую (пн,ср,пт)."
            )
            return
        cron_weekdays = ",".join(resolved)

    data = await state.get_data()
    user = await get_or_create_user(session, message.from_user.id, message.chat.id)

    if not user.user_timezone:
        await message.answer(
            "Не задан часовой пояс. Сначала настрой профиль через /start или /profile."
        )
        await state.clear()
        return

    try:
        trigger = await UserTriggerService.create_trigger(
            session=session,
            user_id=user.id,
            name=data["name"],
            prompt=data["prompt"],
            cron_hour=data["cron_hour"],
            cron_minute=data["cron_minute"],
            cron_weekdays=cron_weekdays,
        )
        await session.commit()

        # Schedule the new trigger job
        try:
            from ...scheduler.job_manager import JobManager
            await JobManager.schedule_user_triggers(session, user)
        except Exception as e:
            logger.warning("Failed to schedule trigger {} for user {}: {}", trigger.id, user.id, e)

        days_label = cron_weekdays or "каждый день"
        await message.answer(
            f"✅ Триггер <b>{html.escape(trigger.name)}</b> создан!\n"
            f"   Время: {trigger.cron_hour:02d}:{trigger.cron_minute:02d}\n"
            f"   Дни: {days_label}\n\n"
            f"Используй /triggers для управления."
        )
    except ValueError as e:
        await message.answer(f"❌ {html.escape(str(e))}")
    except Exception as e:
        logger.exception("Failed to create trigger for user {}: {}", user.id, e)
        await message.answer("Не удалось создать триггер. Попробуй ещё раз.")

    await state.clear()
