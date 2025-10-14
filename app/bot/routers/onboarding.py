from __future__ import annotations
from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter

from ...services.profile_services import get_or_create_user, update_user_profile
from ...utils.validators import clamp_age, is_valid_timezone
from ...utils.timeparse import parse_hhmm
from ...llm.gemini_client import parse_occupation_to_json
from ..states import Onboarding

router = Router(name="onboarding")

# === Start message ===
WELCOME = (
    "Hey, I’m Moti! 💫 I’ll help organize your days and keep you motivated.\n"
    "Let’s set up your profile. What’s your first name?"
)

# === Handlers ===
@router.message(F.text == "/start")
async def cmd_start(message: Message, state: FSMContext, session):
    await get_or_create_user(session, tg_user_id=message.from_user.id, tg_chat_id=message.chat.id)
    await message.answer(WELCOME)
    await state.set_state(Onboarding.name)

@router.message(Onboarding.name, F.text, (F.text.len() > 0))
async def get_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await message.answer("Nice to meet you! How old are you?")
    await state.set_state(Onboarding.age)

@router.message(Onboarding.age, F.text)
async def get_age(message: Message, state: FSMContext):
    age = clamp_age(message.text.strip())
    if age is None:
        await message.answer("Please enter a valid age (5–120).")
        return
    await state.update_data(age=age)
    await message.answer("What’s your IANA timezone? For example: Europe/Berlin, America/New_York, Asia/Tokyo")
    await state.set_state(Onboarding.timezone)

@router.message(Onboarding.timezone, F.text)
async def get_timezone(message: Message, state: FSMContext):
    tz = message.text.strip()
    if not is_valid_timezone(tz):
        await message.answer("That doesn’t look like a valid timezone. Try something like Europe/Berlin.")
        return
    await state.update_data(timezone=tz)
    await message.answer("What time do you usually wake up? (HH:MM, 24h)")
    await state.set_state(Onboarding.wake_time)

@router.message(Onboarding.wake_time, F.text)
async def get_wake(message: Message, state: FSMContext):
    t = parse_hhmm(message.text.strip())
    if t is None:
        await message.answer("Please use HH:MM format, e.g., 07:30")
        return
    await state.update_data(wake_time=t.isoformat(timespec="minutes"))
    await message.answer("And your usual bedtime? (HH:MM, 24h)")
    await state.set_state(Onboarding.bed_time)

@router.message(Onboarding.bed_time, F.text)
async def get_bed(message: Message, state: FSMContext):
    t = parse_hhmm(message.text.strip())
    if t is None:
        await message.answer("Please use HH:MM format, e.g., 23:00")
        return
    await state.update_data(bed_time=t.isoformat(timespec="minutes"))
    await message.answer(
        "What’s your occupation? Tell me in your own words (what you do, employer, "
        "key responsibilities, schedule, tools/skills)."
    )
    await state.set_state(Onboarding.occupation)

@router.message(Onboarding.occupation, F.text)
async def get_occupation(message: Message, state: FSMContext, session):
    await state.update_data(occupation_text=message.text.strip())

    data = await state.get_data()
    user = await get_or_create_user(session, message.from_user.id, message.chat.id)

    from datetime import time
    wake = time.fromisoformat(data["wake_time"])
    bed = time.fromisoformat(data["bed_time"])

    await update_user_profile(
        session, user,
        name=data["name"],
        age=data["age"],
        timezone=data["timezone"],
        wake_time=wake,
        bed_time=bed
    )

    await message.answer("Thanks! I’m structuring your occupation details… one moment ⏳")

    occ_struct = await parse_occupation_to_json(message.text.strip())
    await update_user_profile(session, user, occupation_json=occ_struct)

    from ...services.settings_service import SettingsService
    from ...scheduler.job_manager import JobManager

    user_settings = await SettingsService.get_or_create(session, user.id)
    await session.commit()

    JobManager.schedule_user_jobs(user, user_settings)

    summary = (
        f"Here's what I've got:\n"
        f"- Name: <b>{data['name']}</b>\n"
        f"- Age: <b>{data['age']}</b>\n"
        f"- Timezone: <b>{data['timezone']}</b>\n"
        f"- Wake: <b>{data['wake_time']}</b>\n"
        f"- Bed: <b>{data['bed_time']}</b>\n"
        f"- Occupation: <code>{occ_struct.get('title', 'N/A')}</code>\n\n"
        f"✅ Profile complete! I've scheduled morning check-ins at your wake time "
        f"and evening wrap-ups 1 hour before bedtime.\n\n"
        f"I'll also generate weekly plans every Sunday and monthly plans on the 1st. "
        f"You can customize this with /settings (coming in Phase 5)."
    )
    await message.answer(summary)
    await state.clear()
