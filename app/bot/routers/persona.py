from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from ...services.profile_services import get_or_create_user
from ...services.settings_service import SettingsService

persona_router = Router(name="persona")

PERSONAS = {
    "strict": {
        "ru": {
            "name": "🔥 Жёсткий ментор",
            "preview": "Без соплей и нытья. Я буду гнать тебя вперёд пинками и матом. Ты хочешь результат? Тогда терпи.\n\n<i>Пример: «Да мне насрать, что устал. Поставила тебе напоминалку. Работай.»</i>",
        },
        "en": {
            "name": "🔥 Drill Sergeant",
            "preview": "No sugarcoating. I'll push you hard with blunt truths and zero patience for excuses. Results only.\n\n<i>Example: 'I don't care if you're tired. Set your reminder. Get to work.'</i>",
        },
    },
    "friendly": {
        "ru": {
            "name": "😊 Добрый друг",
            "preview": "Тёплая поддержка, никакого давления. Я рядом, чтобы помочь и порадоваться вместе с тобой.\n\n<i>Пример: «Ей, ты молодец что написал! Давай вместе разберёмся, всё получится 🌟»</i>",
        },
        "en": {
            "name": "😊 Friendly Buddy",
            "preview": "Warm, supportive, zero pressure. I'm here to cheer you on and celebrate every win together.\n\n<i>Example: 'Hey, I'm so glad you reached out! Let's figure this out together 🌟'</i>",
        },
    },
    "coach": {
        "ru": {
            "name": "💼 Деловой коуч",
            "preview": "Профессиональный и структурированный. Цели, метрики, конкретные шаги — без лишних эмоций.\n\n<i>Пример: «Принято. Ставлю напоминание на 9:00. Рекомендую метод Помодоро. Что в приоритете сегодня?»</i>",
        },
        "en": {
            "name": "💼 Executive Coach",
            "preview": "Professional and structured. Goals, metrics, action steps — no fluff, just outcomes.\n\n<i>Example: 'Noted. Reminder set for 9AM. I recommend Pomodoro method. What's your priority today?'</i>",
        },
    },
    "zen": {
        "ru": {
            "name": "🧘 Спокойный мудрец",
            "preview": "Философский и неспешный. Метафоры, осознанность, взгляд на большую картину.\n\n<i>Пример: «Река не борется с течением. Я создала напоминание. А пока — что мешает тебе начать?»</i>",
        },
        "en": {
            "name": "🧘 Zen Master",
            "preview": "Philosophical and unhurried. Metaphors, mindfulness, and the bigger picture.\n\n<i>Example: 'A river flows with the current, not against it. Reminder set. What stands between you and starting?'</i>",
        },
    },
    "hype": {
        "ru": {
            "name": "⚡ Энерджайзер",
            "preview": "МАКСИМАЛЬНАЯ ЭНЕРГИЯ! Каждый шаг — это ПОБЕДА! Мы взорвём этот день вместе! 🔥🚀💪\n\n<i>Пример: «ТЫ МОЖЕШЬ! Поставила напоминание — и когда оно придёт, ты ПОКОРИШЬ этот день! LET'S GOOO! 🔥»</i>",
        },
        "en": {
            "name": "⚡ Hype Machine",
            "preview": "MAXIMUM ENERGY! Every step is a WIN! We're going to CRUSH this day together! 🔥🚀💪\n\n<i>Example: 'YOU GOT THIS! Reminder set — when it fires, you're going to DOMINATE the day! LET'S GOOOO! 🔥'</i>",
        },
    },
}

CONFIRMATION_MESSAGES = {
    "strict": {
        "ru": "Ладно. Будем жёстко. Не ной потом.",
        "en": "Fine. We do this the hard way. Don't come crying later.",
    },
    "friendly": {
        "ru": "Отлично! Буду рядом и поддержу тебя 😊",
        "en": "Yay! I'll be right here cheering you on 😊",
    },
    "coach": {
        "ru": "Принято. Переходим в деловой формат.",
        "en": "Confirmed. Switching to professional mode.",
    },
    "zen": {
        "ru": "Как река меняет русло... Так и наш путь обретает новую форму.",
        "en": "As the river finds a new course... so too does our journey take new form.",
    },
    "hype": {
        "ru": "YOOO LET'S GOOOO! 🔥🔥🔥 НОВЫЙ ВАЙБ ВКЛЮЧЁН! 💪⚡🚀",
        "en": "YOOO LET'S GOOOO! 🔥🔥🔥 NEW MODE ACTIVATED! 💪⚡🚀",
    },
}


def _get_language(settings) -> str:
    prefs = getattr(settings, "summary_preferences_json", None) or {}
    return prefs.get("language", "ru") if isinstance(prefs, dict) else "ru"


def _build_persona_menu(current_persona: str, language: str) -> tuple[str, InlineKeyboardMarkup]:
    current_data = PERSONAS.get(current_persona, PERSONAS["strict"])
    current_name = current_data[language]["name"]

    if language == "ru":
        text = f"🎭 <b>Выбери стиль общения</b>\n\nТекущий: {current_name}"
    else:
        text = f"🎭 <b>Choose your communication style</b>\n\nCurrent: {current_name}"

    buttons = []
    for persona_id, persona_data in PERSONAS.items():
        name = persona_data[language]["name"]
        label = f"✅ {name}" if persona_id == current_persona else name
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"persona_preview:{persona_id}")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    return text, keyboard


@persona_router.message(Command("persona"))
async def cmd_persona(message: Message, session: AsyncSession) -> None:
    user = await get_or_create_user(session, message.from_user.id, message.chat.id)
    settings = await SettingsService.get_or_create(session, user.id)

    language = _get_language(settings)
    current_persona = getattr(settings, "bot_persona", "strict") or "strict"

    text, keyboard = _build_persona_menu(current_persona, language)
    await message.answer(text, reply_markup=keyboard)


@persona_router.callback_query(F.data.startswith("persona_preview:"))
async def cb_persona_preview(callback: CallbackQuery, session: AsyncSession) -> None:
    _, persona_id = callback.data.split(":", 1)

    if persona_id not in PERSONAS:
        persona_id = "strict"

    user = await get_or_create_user(session, callback.from_user.id, callback.message.chat.id)
    settings = await SettingsService.get_or_create(session, user.id)
    language = _get_language(settings)

    persona_data = PERSONAS[persona_id][language]
    name = persona_data["name"]
    preview = persona_data["preview"]

    if language == "ru":
        text = f"<b>{name}</b>\n\n{preview}"
        select_label = "✅ Выбрать"
        back_label = "← Назад"
    else:
        text = f"<b>{name}</b>\n\n{preview}"
        select_label = "✅ Select"
        back_label = "← Back"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=select_label, callback_data=f"persona_select:{persona_id}")],
            [InlineKeyboardButton(text=back_label, callback_data="persona_menu")],
        ]
    )

    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@persona_router.callback_query(F.data.startswith("persona_select:"))
async def cb_persona_select(callback: CallbackQuery, session: AsyncSession) -> None:
    _, persona_id = callback.data.split(":", 1)

    if persona_id not in PERSONAS:
        persona_id = "strict"

    user = await get_or_create_user(session, callback.from_user.id, callback.message.chat.id)
    settings = await SettingsService.get_or_create(session, user.id)
    language = _get_language(settings)

    settings.bot_persona = persona_id
    if hasattr(settings, "touch"):
        settings.touch()
    session.add(settings)
    await session.commit()

    logger.info("User {} changed persona to {}", user.id, persona_id)

    confirmation = CONFIRMATION_MESSAGES[persona_id][language]

    if language == "ru":
        footer = "Используй /persona чтобы изменить в любое время."
    else:
        footer = "Use /persona to change anytime."

    text = f"{confirmation}\n\n<i>{footer}</i>"

    await callback.message.edit_text(text)
    await callback.answer()


@persona_router.callback_query(F.data == "persona_menu")
async def cb_persona_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    user = await get_or_create_user(session, callback.from_user.id, callback.message.chat.id)
    settings = await SettingsService.get_or_create(session, user.id)

    language = _get_language(settings)
    current_persona = getattr(settings, "bot_persona", "strict") or "strict"

    text, keyboard = _build_persona_menu(current_persona, language)
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()
