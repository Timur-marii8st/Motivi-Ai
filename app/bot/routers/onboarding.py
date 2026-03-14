from __future__ import annotations
import asyncio

from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from loguru import logger

from ...config import settings
from ...services.profile_services import get_or_create_user, update_user_profile
from ...utils.validators import is_valid_timezone
from ...utils.timeparse import parse_hhmm
from ...utils.timezone_resolver import resolve_timezone_from_city
from ...llm.gemini_client import parse_occupation_to_json
from ..states import Onboarding

router = Router(name="onboarding")

@router.message(F.text == "/cancel")
async def cancel_onboarding(message: Message, state: FSMContext):
    """Cancel onboarding process."""
    current_state = await state.get_state()
    if current_state is None or not current_state.startswith("Onboarding"):
        return  # Not in onboarding, let other handlers deal with it
    
    await state.clear()
    await message.answer(
        "❌ Онбординг отменен. Ты можешь начать заново с /start или просто написать мне."
    )

# === Start message ===
WELCOME = (
    "Привет, я Мотиви! 💫 Я помогу тебе организовать день и поддержу мотивацию.\n"
    "Давай настроим твой профиль. Как тебя зовут?     (Если хочешь пропустить этот и любой другой вопрос от меня, отправь 'пропустить' или 'skip'"
)

SKIP_TOKENS = {'/skip', 'skip', 'пропустить'}

# === Handlers ===
@router.message(F.text.startswith("/start"))
async def cmd_start(message: Message, state: FSMContext, session):
    user = await get_or_create_user(session, tg_user_id=message.from_user.id, tg_chat_id=message.chat.id)

    # Handle referral deep link: /start ref_XXXXX
    text = message.text.strip()
    if " " in text:
        payload = text.split(" ", 1)[1].strip()
        if payload.startswith("ref_"):
            referral_code = payload[4:]
            try:
                from .referral import handle_referral_deep_link
                await handle_referral_deep_link(session, referral_code, user.id)
                await session.commit()
            except Exception as e:
                logger.exception("Referral deep link processing failed: {}", e)
            # Store referral info in FSM for later use
            await state.update_data(referral_code=referral_code)

    await message.answer(WELCOME)
    await state.set_state(Onboarding.name)

@router.message(Onboarding.name, F.text, (F.text.len() > 0))
async def get_name(message: Message, state: FSMContext):
    txt = message.text.strip()
    if txt.lower() in SKIP_TOKENS:
        await state.update_data(name=None)
        await message.answer("Ок, имя можно указать позже через /profile. В каком городе ты живёшь? Просто название города (например: Moscow, Berlin или Новосибирск)")
        await state.set_state(Onboarding.timezone)
        return

    await state.update_data(name=txt)
    await message.answer("Приятно познакомиться! В каком городе ты живёшь? Просто название города (например: Moscow, Berlin или Новосибирск)")
    await state.set_state(Onboarding.timezone)

@router.message(Onboarding.timezone, F.text)
async def get_timezone(message: Message, state: FSMContext):
    txt = message.text.strip()
    if txt.lower() in SKIP_TOKENS:
        await state.update_data(timezone=None)
        await message.answer("Ок, часовой пояс можно указать позже. Во сколько ты обычно просыпаешься? (ЧЧ:ММ, 24ч)")
        await state.set_state(Onboarding.wake_time)
        return

    # Allow full IANA timezone input as fallback
    if is_valid_timezone(txt):
        await state.update_data(timezone=txt)
        await message.answer("Спасибо! Во сколько ты обычно просыпаешься? (ЧЧ:ММ, 24ч)")
        await state.set_state(Onboarding.wake_time)
        return

    # Try resolve by city name
    resolved = resolve_timezone_from_city(txt)
    if resolved is None:
        await message.answer(
            "Не удалось найти часовой пояс по указанному городу. Попробуй другое название города или укажи IANA (например Europe/Berlin). Или отправь /skip, чтобы пропустить."
        )
        return
    if isinstance(resolved, list):
        # ambiguous
        opts = "\n".join(f"- {o}" for o in resolved[:10])
        await message.answer(
            f"Найдено несколько вариантов для этого города. Уточни, пожалуйста, указав один из вариантов IANA:\n{opts}"
        )
        return

    # resolved is a string timezone
    await state.update_data(timezone=resolved)
    await message.answer("Отлично — часовой пояс установлен. Во сколько ты обычно просыпаешься? (ЧЧ:ММ, 24ч)")
    await state.set_state(Onboarding.wake_time)

@router.message(Onboarding.wake_time, F.text)
async def get_wake(message: Message, state: FSMContext):
    txt = message.text.strip()
    if txt.lower() in SKIP_TOKENS:
        await state.update_data(wake_time=None)
        await message.answer("Ок, пропустим. А когда обычно ложишься спать? (ЧЧ:ММ, 24ч)")
        await state.set_state(Onboarding.bed_time)
        return

    t = parse_hhmm(txt)
    if t is None:
        await message.answer("Пожалуйста, используй формат ЧЧ:ММ, например 07:30 или отправь /skip")
        return
    await state.update_data(wake_time=t.isoformat(timespec="minutes"))
    await message.answer("А когда обычно ложишься спать? (ЧЧ:ММ, 24ч)")
    await state.set_state(Onboarding.bed_time)

@router.message(Onboarding.bed_time, F.text)
async def get_bed(message: Message, state: FSMContext):
    txt = message.text.strip()
    if txt.lower() in SKIP_TOKENS:
        await state.update_data(bed_time=None)
        await message.answer(
            "Ок, пропустим. Кем ты работаешь? Чем занимаешься? Расскажи своими словами (должность, компания, основные задачи, график, инструменты/навыки)."
        )
        await state.set_state(Onboarding.occupation)
        return

    t = parse_hhmm(txt)
    if t is None:
        await message.answer("Пожалуйста, используй формат ЧЧ:ММ, например 23:00 или отправь /skip")
        return
    await state.update_data(bed_time=t.isoformat(timespec="minutes"))
    await message.answer(
        "Кем ты работаешь? Чем занимаешься? Расскажи своими словами (должность, компания, "
        "основные задачи, график, инструменты/навыки)."
    )
    await state.set_state(Onboarding.occupation)

@router.message(StateFilter(Onboarding), F.text.lower().in_(SKIP_TOKENS))
async def handle_skip_and_forward(message: Message, state: FSMContext, session):

    st = (await state.get_state()).split(':')[-1]
    if st == 'name':
        await state.update_data(name=None)
        await message.answer("Ок, имя можно указать позже через /profile. В каком городе ты живёшь? Просто название города (например: Moscow, Berlin или Новосибирск)")
        await state.set_state(Onboarding.timezone)
        return
    if st == 'timezone':
        await state.update_data(timezone=None)
        await message.answer("Ок, часовой пояс можно указать позже. Во сколько ты обычно просыпаешься? (ЧЧ:ММ, 24ч)")
        await state.set_state(Onboarding.wake_time)
        return
    if st == 'wake_time':
        await state.update_data(wake_time=None)
        await message.answer("Ок, пропустим. А когда обычно ложишься спать? (ЧЧ:ММ, 24ч)")
        await state.set_state(Onboarding.bed_time)
        return
    if st == 'bed_time':
        await state.update_data(bed_time=None)
        await message.answer("Ок, пропустим. Кем ты работаешь? Расскажи своими словами (должность, компания, основные задачи, график, инструменты/навыки).")
        await state.set_state(Onboarding.occupation)
        return
    if st == 'occupation':
        await state.update_data(occupation_text=None)
        # Proceed to finalize onboarding
        await finalize_onboarding(message, state, session)
        return


@router.message(Onboarding.occupation, F.text)
async def get_occupation(message: Message, state: FSMContext, session):
    await state.update_data(occupation_text=message.text.strip())
    await finalize_onboarding(message, state, session)


async def finalize_onboarding(message: Message, state: FSMContext, session):
    data = await state.get_data()
    user = await get_or_create_user(session, message.from_user.id, message.chat.id)

    from datetime import time
    wake = None
    bed = None
    if data.get('wake_time'):
        try:
            wake = time.fromisoformat(data['wake_time'])
        except Exception:
            wake = None
    if data.get('bed_time'):
        try:
            bed = time.fromisoformat(data['bed_time'])
        except Exception:
            bed = None

    await update_user_profile(
        session, user,
        name=data.get('name'),
        timezone=data.get('timezone'),
        wake_time=wake,
        bed_time=bed
    )

    await message.answer("Спасибо! Структурирую информацию о твоей деятельности… одну секунду ⏳")

    occ_struct = None
    if data.get('occupation_text'):
        occ_struct = await parse_occupation_to_json(data.get('occupation_text'))
        await update_user_profile(session, user, occupation_json=occ_struct)

    from ...services.settings_service import SettingsService
    from ...scheduler.job_manager import JobManager

    user_settings = await SettingsService.get_or_create(session, user.id)

    # Detect and persist language preference from Telegram locale
    lang_code = (message.from_user.language_code or "ru").lower()
    lang = "en" if lang_code.startswith("en") else "ru"
    prefs = user_settings.summary_preferences_json or {}
    prefs["language"] = lang
    user_settings.summary_preferences_json = prefs
    user_settings.touch()
    session.add(user_settings)

    await session.commit()

    JobManager.schedule_user_jobs(user, user_settings)

    summary = (
        f"Вот что я записала:\n"
        f"- Имя: <b>{data.get('name') or 'Не указано'}</b>\n"
        f"- Часовой пояс: <b>{data.get('timezone') or 'Не указан'}</b>\n"
        f"- Подъем: <b>{data.get('wake_time') or 'Не указан'}</b>\n"
        f"- Отбой: <b>{data.get('bed_time') or 'Не указан'}</b>\n"
        f"- Деятельность: <code>{(occ_struct or {}).get('title', 'Не определено')}</code>\n\n"
        f"✅ Профиль готов! Я запланировала утренние приветствия во время твоего пробуждения "
        f"и вечерние итоги за час до сна (если указаны времена).\n\n"
        f"Также я буду составлять планы на неделю по воскресеньям и на месяц 1-го числа. "
        f"Ты сможешь настроить это через /settings (скоро)."
    )
    await message.answer(summary)
    await state.clear()

    # ── Onboarding Quick Win: suggest top 3 priorities immediately ──
    if settings.is_feature_enabled("F008_ONBOARDING_QUICK_WIN"):
        asyncio.create_task(_trigger_quick_win(user, session))

    # ── Schedule memory reveals at day 3 and day 7 ──
    try:
        from ...services.memory_reveal_service import MemoryRevealService
        MemoryRevealService.schedule_memory_reveals(user.id, user.created_at)
    except Exception as e:
        logger.exception("Failed to schedule memory reveals for user {}: {}", user.id, e)

    # ── Schedule premium taste prompt at trial day 5 ──
    try:
        from ...services.premium_taste_service import PremiumTasteService
        PremiumTasteService.schedule_trial_day5_job(user.id, user.created_at)
    except Exception as e:
        logger.exception("Failed to schedule premium taste for user {}: {}", user.id, e)


async def _trigger_quick_win(user, session) -> None:
    """Fire a mini morning check-in immediately after onboarding (background)."""
    try:
        from ...services.proactive_flows import ProactiveFlows

        flows = ProactiveFlows(session)
        await flows._run_flow(
            user=user,
            prompt=(
                "The user just completed onboarding. Based on what you know about them, "
                "suggest their top 3 priorities for today. Be concise and actionable. "
                "This is their very first interaction with you beyond setup — make it count."
            ),
            greeting="Now that I know a bit about you, here are your priorities for today 🎯",
            top_k=3,
        )
        logger.info("Quick win sent to user {}", user.id)
    except Exception as e:
        logger.exception("Quick win failed for user {}: {}", user.id, e)