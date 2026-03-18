from __future__ import annotations
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from ...services.profile_services import get_or_create_user, update_user_profile
from ...services.core_memory_service import CoreMemoryService
from ...services.profile_completeness_service import ProfileCompletenessService
from ...utils.validators import is_valid_timezone, clamp_age
from ...utils.timeparse import parse_hhmm
from ..states import ProfileEdit
from ...config import settings
import html
import json

router = Router(name="profile")

@router.message(F.text == "/profile")
async def profile_cmd(message: Message, session):
    """Display user profile with edit options."""
    user = await get_or_create_user(session, message.from_user.id, message.chat.id)
    core = await CoreMemoryService.get_or_create(session, user.id)
    pc = await ProfileCompletenessService.get_or_create(session, user.id)
    
    text = (
        f"<b>👤 Профиль</b>\n\n"
        f"<b>Основная информация:</b>\n"
    f"• Имя: {html.escape(user.name) if user.name else 'Не указано'}\n"
        f"• Возраст: {user.age or 'Не указано'}\n"
        f"• Часовой пояс: {user.user_timezone or 'Не указано'}\n"
        f"• Время подъёма: {user.wake_time or 'Не указано'}\n"
        f"• Время отхода ко сну: {user.bed_time or 'Не указано'}\n\n"
        f"<b>Деятельность:</b>\n"
    f"{html.escape(user.occupation_json.get('title', 'Не указано')) if user.occupation_json else 'Не указано'}\n\n"
        f"<b>Заполненность профиля:</b> {pc.score * 100:.0f}%\n"
        f"<b>Всего взаимодействий:</b> {pc.total_interactions}\n"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Изменить имя", callback_data="profile_edit_name")],
        [InlineKeyboardButton(text="✏️ Изменить возраст", callback_data="profile_edit_age")],
        [InlineKeyboardButton(text="✏️ Изменить часовой пояс", callback_data="profile_edit_timezone")],
        [InlineKeyboardButton(text="✏️ Время подъёма/сна", callback_data="profile_edit_times")],
        [InlineKeyboardButton(text="🎯 Цели", callback_data="profile_edit_goals")],
        [InlineKeyboardButton(text="🗑 Удалить аккаунт", callback_data="profile_delete_account")],
    ])
    
    await message.answer(text, reply_markup=keyboard)

@router.callback_query(F.data == "profile_edit_name")
async def edit_name_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()  # Clear any previous state
    await callback.message.answer("Какое у тебя новое имя?")
    await state.set_state(ProfileEdit.name)
    await callback.answer()

@router.message(ProfileEdit.name, F.text)
async def save_name(message: Message, state: FSMContext, session):
    user = await get_or_create_user(session, message.from_user.id, message.chat.id)
    await update_user_profile(session, user, name=message.text.strip())
    await ProfileCompletenessService.update_score(session, user.id)
    await session.commit()
    
    await message.answer(f"✅ Имя обновлено на <b>{html.escape(user.name)}</b>")
    await state.clear()

@router.callback_query(F.data == "profile_edit_age")
async def edit_age_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()  # Clear any previous state
    await callback.message.answer("Сколько тебе лет?")
    await state.set_state(ProfileEdit.age)
    await callback.answer()

@router.message(ProfileEdit.age, F.text)
async def save_age(message: Message, state: FSMContext, session):
    age = clamp_age(message.text.strip())
    if not age:
        await message.answer("Пожалуйста, введи корректный возраст (5-120).")
        return
    
    user = await get_or_create_user(session, message.from_user.id, message.chat.id)
    await update_user_profile(session, user, age=age)
    await ProfileCompletenessService.update_score(session, user.id)
    await session.commit()
    
    await message.answer(f"✅ Возраст обновлён: <b>{age}</b>")
    await state.clear()

@router.callback_query(F.data == "profile_edit_timezone")
async def edit_timezone_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()  # Clear any previous state
    await callback.message.answer("Укажи свой IANA часовой пояс (например, Europe/Berlin, America/New_York):")
    await state.set_state(ProfileEdit.timezone)
    await callback.answer()

@router.message(ProfileEdit.timezone, F.text)
async def save_timezone(message: Message, state: FSMContext, session):
    tz = message.text.strip()
    if not is_valid_timezone(tz):
        await message.answer("Неверный часовой пояс. Попробуй формат IANA, например America/New_York.")
        return
    
    user = await get_or_create_user(session, message.from_user.id, message.chat.id)
    await update_user_profile(session, user, timezone=tz)
    await ProfileCompletenessService.update_score(session, user.id)
    await session.commit()
    
    # Reschedule jobs with new timezone
    from ...services.settings_service import SettingsService
    from ...scheduler.job_manager import JobManager
    
    settings = await SettingsService.get_or_create(session, user.id)
    JobManager.schedule_user_jobs(user, settings)
    
    await message.answer(f"✅ Часовой пояс обновлён на <b>{html.escape(tz)}</b>. Расписанные задания перенастроены.")
    await state.clear()

@router.callback_query(F.data == "profile_edit_times")
async def edit_times_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()  # Clear any previous state
    await callback.message.answer("Укажи время подъёма (ЧЧ:ММ, 24ч):")
    await state.set_state(ProfileEdit.wake_time)
    await callback.answer()

@router.message(ProfileEdit.wake_time, F.text)
async def save_wake_time(message: Message, state: FSMContext):
    wake = parse_hhmm(message.text.strip())
    if not wake:
        await message.answer("Неверный формат. Используй ЧЧ:ММ, например 07:30.")
        return
    
    await state.update_data(wake_time=wake.isoformat())
    await message.answer("Теперь укажи время отхода ко сну (ЧЧ:ММ):")
    await state.set_state("ProfileEdit:bed_time")

@router.message(ProfileEdit.bed_time, F.text)
async def save_bed_time(message: Message, state: FSMContext, session):
    bed = parse_hhmm(message.text.strip())
    if not bed:
        await message.answer("Неверный формат. Используй ЧЧ:ММ, например 23:00.")
        return
    
    data = await state.get_data()
    from datetime import time
    wake = time.fromisoformat(data["wake_time"])
    
    user = await get_or_create_user(session, message.from_user.id, message.chat.id)
    await update_user_profile(session, user, wake_time=wake, bed_time=bed)
    await ProfileCompletenessService.update_score(session, user.id)
    await session.commit()
    
    # Reschedule jobs
    from ...services.settings_service import SettingsService
    from ...scheduler.job_manager import JobManager
    
    settings = await SettingsService.get_or_create(session, user.id)
    JobManager.schedule_user_jobs(user, settings)
    
    await message.answer(f"✅ Время обновлено: Подъём <b>{html.escape(str(wake))}</b>, Сон <b>{html.escape(str(bed))}</b>. Задания перенастроены.")
    await state.clear()

@router.callback_query(F.data == "profile_edit_goals")
async def edit_goals_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()  # Clear any previous state
    await callback.message.answer("Опиши свои цели (например: 'Накачаться, выучить Python, читать больше'):")
    await state.set_state(ProfileEdit.goals)
    await callback.answer()

@router.message(ProfileEdit.goals, F.text)
async def save_goals(message: Message, state: FSMContext, session):
    """Save user goals to core memory."""
    user = await get_or_create_user(session, message.from_user.id, message.chat.id)
    goals_text = message.text.strip()
    
    # Store goals in core memory
    from ...services.core_memory_service import CoreMemoryService
    from ...embeddings.embedding_client import EmbeddingClient

    embeddings = EmbeddingClient()
    core_service = CoreMemoryService(embeddings)
    
    fact_text = f"User goals: {goals_text}"
    await core_service.store_core(session, user.id, fact_text)
    await ProfileCompletenessService.update_score(session, user.id)
    await session.commit()
    
    await message.answer(f"✅ Цели сохранены в память:\n<b>{html.escape(goals_text)}</b>")
    await state.clear()

@router.message(F.text == "/cancel")
async def cancel_handler(message: Message, state: FSMContext):
    """Cancel any active FSM state."""
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("Нечего отменять.")
        return
    
    await state.clear()
    await message.answer("❌ Действие отменено. Можешь продолжить с /profile или просто написать мне.")

@router.callback_query(F.data == "profile_delete_account")
async def delete_account_callback(callback: CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Yes, delete my account", callback_data="profile_delete_confirm"),
            InlineKeyboardButton(text="❌ Cancel", callback_data="profile_delete_cancel"),
        ]
    ])
    
    await callback.message.answer(
        "⚠️ <b>ВНИМАНИЕ:</b> Это удалит все твои данные безвозвратно:\n"
        "• Профиль и настройки\n"
        "• Задачи и привычки\n"
        "• OAuth токены\n\n"
        "И все что я помню о тебе и о том, что мы пережили вместе 😢\n"
        "Это действие нельзя будет отменить. Ты уверен(а)?",
        reply_markup=keyboard
    )
    await callback.answer()

@router.callback_query(F.data == "profile_delete_cancel")
async def delete_cancel(callback: CallbackQuery):
    await callback.message.answer("❌ Удаление аккаунта отменено.")
    await callback.answer()

@router.callback_query(F.data == "profile_delete_confirm")
async def delete_confirm(callback: CallbackQuery, session):
    user = await get_or_create_user(session, callback.from_user.id, callback.message.chat.id)
    
    # Full cleanup
    from ...services.account_service import AccountService
    await AccountService.delete_user_account(session, user.id)
    await session.commit()
    
    await callback.message.answer(
        "✅ Твой аккаунт и все данные были безвозвратно удалены.\n\n"
        "Спасибо, что использовал(а) Motivi_AI. Ты всегда можешь начать заново с /start."
    )
    await callback.answer()