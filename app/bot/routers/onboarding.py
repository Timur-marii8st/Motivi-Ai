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
    "Привет, я Мотиви! 💫 Я помогу тебе организовать день и поддержу мотивацию.\n"
    "Давай настроим твой профиль. Как тебя зовут?"
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
    await message.answer("Приятно познакомиться! Сколько тебе лет?")
    await state.set_state(Onboarding.age)

@router.message(Onboarding.age, F.text)
async def get_age(message: Message, state: FSMContext):
    age = clamp_age(message.text.strip())
    if age is None:
        await message.answer("Пожалуйста, введи корректный возраст (от 5 до 120).")
        return
    await state.update_data(age=age)
    await message.answer("Какой у тебя часовой пояс (IANA)? Например: Europe/Moscow, Asia/Novosibirsk или Europe/Berlin")
    await state.set_state(Onboarding.timezone)

@router.message(Onboarding.timezone, F.text)
async def get_timezone(message: Message, state: FSMContext):
    tz = message.text.strip()
    if not is_valid_timezone(tz):
        await message.answer("Похоже, это неверный формат. Попробуй что-то вроде Europe/Moscow.")
        return
    await state.update_data(timezone=tz)
    await message.answer("Во сколько ты обычно просыпаешься? (ЧЧ:ММ, 24ч)")
    await state.set_state(Onboarding.wake_time)

@router.message(Onboarding.wake_time, F.text)
async def get_wake(message: Message, state: FSMContext):
    t = parse_hhmm(message.text.strip())
    if t is None:
        await message.answer("Пожалуйста, используй формат ЧЧ:ММ, например 07:30")
        return
    await state.update_data(wake_time=t.isoformat(timespec="minutes"))
    await message.answer("А когда обычно ложишься спать? (ЧЧ:ММ, 24ч)")
    await state.set_state(Onboarding.bed_time)

@router.message(Onboarding.bed_time, F.text)
async def get_bed(message: Message, state: FSMContext):
    t = parse_hhmm(message.text.strip())
    if t is None:
        await message.answer("Пожалуйста, используй формат ЧЧ:ММ, например 23:00")
        return
    await state.update_data(bed_time=t.isoformat(timespec="minutes"))
    await message.answer(
        "Кем ты работаешь? Расскажи своими словами (должность, компания, "
        "основные задачи, график, инструменты/навыки)."
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

    await message.answer("Спасибо! Структурирую информацию о твоей деятельности… одну секунду ⏳")

    occ_struct = await parse_occupation_to_json(message.text.strip())
    await update_user_profile(session, user, occupation_json=occ_struct)

    from ...services.settings_service import SettingsService
    from ...scheduler.job_manager import JobManager

    user_settings = await SettingsService.get_or_create(session, user.id)
    await session.commit()

    JobManager.schedule_user_jobs(user, user_settings)

    summary = (
        f"Вот что я записала:\n"
        f"- Имя: <b>{data['name']}</b>\n"
        f"- Возраст: <b>{data['age']}</b>\n"
        f"- Часовой пояс: <b>{data['timezone']}</b>\n"
        f"- Подъем: <b>{data['wake_time']}</b>\n"
        f"- Отбой: <b>{data['bed_time']}</b>\n"
        f"- Деятельность: <code>{occ_struct.get('title', 'Не определено')}</code>\n\n"
        f"✅ Профиль готов! Я запланировала утренние приветствия во время твоего пробуждения "
        f"и вечерние итоги за час до сна.\n\n"
        f"Также я буду составлять планы на неделю по воскресеньям и на месяц 1-го числа. "
        f"Ты сможешь настроить это через /settings (скоро)."
    )
    await message.answer(summary)
    await state.clear()