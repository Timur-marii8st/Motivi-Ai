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
        f"<b>👤 Your Profile</b>\n\n"
        f"<b>Basic Info:</b>\n"
    f"• Name: {html.escape(user.name) if user.name else 'Not set'}\n"
        f"• Age: {user.age or 'Not set'}\n"
        f"• Timezone: {user.user_timezone or 'Not set'}\n"
        f"• Wake time: {user.wake_time or 'Not set'}\n"
        f"• Bedtime: {user.bed_time or 'Not set'}\n\n"
        f"<b>Occupation:</b>\n"
    f"{html.escape(user.occupation_json.get('title', 'Not set')) if user.occupation_json else 'Not set'}\n\n"
        f"<b>Goals:</b>\n"
    f"{html.escape(json.dumps(core.goals_json, ensure_ascii=False)) if core.goals_json else 'Not set'}\n\n"
        f"<b>Profile Completeness:</b> {pc.score * 100:.0f}%\n"
        f"<b>Total Interactions:</b> {pc.total_interactions}\n"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Edit Name", callback_data="profile_edit_name")],
        [InlineKeyboardButton(text="✏️ Edit Age", callback_data="profile_edit_age")],
        [InlineKeyboardButton(text="✏️ Edit Timezone", callback_data="profile_edit_timezone")],
        [InlineKeyboardButton(text="✏️ Edit Wake/Bed Times", callback_data="profile_edit_times")],
        [InlineKeyboardButton(text="🎯 Edit Goals", callback_data="profile_edit_goals")],
        [InlineKeyboardButton(text="🗑 Delete Account", callback_data="profile_delete_account")],
    ])
    
    await message.answer(text, reply_markup=keyboard)

@router.callback_query(F.data == "profile_edit_name")
async def edit_name_callback(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("What's your new name?")
    await state.set_state("ProfileEdit:name")
    await callback.answer()

@router.message(ProfileEdit.name, F.text)
async def save_name(message: Message, state: FSMContext, session):
    user = await get_or_create_user(session, message.from_user.id, message.chat.id)
    await update_user_profile(session, user, name=message.text.strip())
    await ProfileCompletenessService.update_score(session, user.id)
    await session.commit()
    
    await message.answer(f"✅ Name updated to <b>{html.escape(user.name)}</b>")
    await state.clear()

@router.callback_query(F.data == "profile_edit_age")
async def edit_age_callback(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("What's your age?")
    await state.set_state("ProfileEdit:age")
    await callback.answer()

@router.message(ProfileEdit.age, F.text)
async def save_age(message: Message, state: FSMContext, session):
    age = clamp_age(message.text.strip())
    if not age:
        await message.answer("Please enter a valid age (5-120).")
        return
    
    user = await get_or_create_user(session, message.from_user.id, message.chat.id)
    await update_user_profile(session, user, age=age)
    await ProfileCompletenessService.update_score(session, user.id)
    await session.commit()
    
    await message.answer(f"✅ Age updated to <b>{age}</b>")
    await state.clear()

@router.callback_query(F.data == "profile_edit_timezone")
async def edit_timezone_callback(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Enter your IANA timezone (e.g., Europe/Berlin, America/New_York):")
    await state.set_state("ProfileEdit:timezone")
    await callback.answer()

@router.message(ProfileEdit.timezone, F.text)
async def save_timezone(message: Message, state: FSMContext, session):
    tz = message.text.strip()
    if not is_valid_timezone(tz):
        await message.answer("Invalid timezone. Try again with IANA format (e.g., America/New_York).")
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
    
    await message.answer(f"✅ Timezone updated to <b>{html.escape(tz)}</b>. Your scheduled jobs have been rescheduled.")
    await state.clear()

@router.callback_query(F.data == "profile_edit_times")
async def edit_times_callback(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Enter your wake time (HH:MM, 24h format):")
    await state.set_state("ProfileEdit:wake_time")
    await callback.answer()

@router.message(ProfileEdit.wake_time, F.text)
async def save_wake_time(message: Message, state: FSMContext):
    wake = parse_hhmm(message.text.strip())
    if not wake:
        await message.answer("Invalid format. Use HH:MM (e.g., 07:30).")
        return
    
    await state.update_data(wake_time=wake.isoformat())
    await message.answer("Now enter your bedtime (HH:MM):")
    await state.set_state("ProfileEdit:bed_time")

@router.message(ProfileEdit.bed_time, F.text)
async def save_bed_time(message: Message, state: FSMContext, session):
    bed = parse_hhmm(message.text.strip())
    if not bed:
        await message.answer("Invalid format. Use HH:MM (e.g., 23:00).")
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
    
    await message.answer(f"✅ Times updated: Wake <b>{html.escape(str(wake))}</b>, Bed <b>{html.escape(str(bed))}</b>. Jobs rescheduled.")
    await state.clear()

@router.callback_query(F.data == "profile_edit_goals")
async def edit_goals_callback(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Describe your goals (e.g., 'Get fit, learn Python, read more'):")
    await state.set_state("ProfileEdit:goals")
    await callback.answer()

@router.message(ProfileEdit.goals, F.text)
async def save_goals(message: Message, state: FSMContext, session):
    user = await get_or_create_user(session, message.from_user.id, message.chat.id)
    goals_text = message.text.strip()
    
    # Parse with LLM
    from ...llm.gemini_client import client
    
    prompt = f"Extract goals from this text as a JSON array of strings: {goals_text}"
    try:
        response = await client.aio.models.generate_content(
            model=settings.GEMINI_MODEL_ID,
            contents=prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        goals_json = response.json() if hasattr(response, 'json') else {"goals": [goals_text]}
    except Exception:
        goals_json = {"goals": [goals_text]}
    
    await CoreMemoryService.update_goals(session, user.id, goals_json)
    await ProfileCompletenessService.update_score(session, user.id)
    await session.commit()
    
    await message.answer(f"✅ Goals updated:\n<code>{html.escape(json.dumps(goals_json, ensure_ascii=False))}</code>")
    await state.clear()

@router.callback_query(F.data == "profile_delete_account")
async def delete_account_callback(callback: CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Yes, delete my account", callback_data="profile_delete_confirm"),
            InlineKeyboardButton(text="❌ Cancel", callback_data="profile_delete_cancel"),
        ]
    ])
    
    await callback.message.answer(
        "⚠️ <b>WARNING:</b> This will permanently delete all your data:\n"
        "• Profile and settings\n"
        "• All memories and episodes\n"
        "• Tasks and habits\n"
        "• OAuth tokens\n\n"
        "This action cannot be undone. Are you sure?",
        reply_markup=keyboard
    )
    await callback.answer()

@router.callback_query(F.data == "profile_delete_cancel")
async def delete_cancel(callback: CallbackQuery):
    await callback.message.answer("❌ Account deletion cancelled.")
    await callback.answer()

@router.callback_query(F.data == "profile_delete_confirm")
async def delete_confirm(callback: CallbackQuery, session):
    user = await get_or_create_user(session, callback.from_user.id, callback.message.chat.id)
    
    # Full cleanup
    from ...services.account_service import AccountService
    await AccountService.delete_user_account(session, user.id)
    await session.commit()
    
    await callback.message.answer(
        "✅ Your account and all data have been permanently deleted.\n\n"
        "Thank you for using Motivi_AI. You can always start fresh with /start."
    )
    await callback.answer()