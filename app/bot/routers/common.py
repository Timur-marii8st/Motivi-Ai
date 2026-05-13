from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router(name="common")


COMMAND_GROUPS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "Основное",
        [
            ("/start", "запустить или пройти онбординг заново"),
            ("/help", "короткая справка"),
            ("/commands", "полный список команд"),
            ("/cancel", "отменить текущее действие"),
            ("/settings", "настройки бота"),
            ("/profile", "профиль и его редактирование"),
            ("/break", "включить break mode"),
            ("/export_data", "экспорт данных"),
        ],
    ),
    (
        "Планы и привычки",
        [
            ("/habits", "список привычек"),
            ("/add_habit", "создать привычку"),
            ("/log_habit <id>", "отметить выполнение привычки"),
            ("/triggers", "список пользовательских триггеров"),
            ("/add_trigger", "создать триггер"),
        ],
    ),
    (
        "Календарь и память",
        [
            ("/connect_calendar", "подключить Google Calendar"),
            ("/my_memories", "посмотреть сохраненные факты"),
            ("/correct", "исправить память о себе"),
            ("/story", "история и саммари"),
            ("/persona", "выбрать персональность бота"),
        ],
    ),
    (
        "Юзербот",
        [
            ("/connect_userbot", "подключить личный Telegram-аккаунт"),
            ("/disconnect_userbot", "отключить юзербот"),
            ("/userbot_interests", "настроить интересы для каналов"),
            ("/userbot_pending", "очередь ожидающих reply suggestions"),
        ],
    ),
    (
        "Подписка и прогресс",
        [
            ("/subscribe", "оформить подписку"),
            ("/referral", "реферальная ссылка"),
            ("/level", "уровень и XP"),
            ("/badges", "значки"),
            ("/leaderboard", "лидерборд"),
        ],
    ),
]


def _commands_text() -> str:
    sections: list[str] = ["<b>Список команд</b>"]
    for title, commands in COMMAND_GROUPS:
        sections.append(f"\n<b>{title}</b>")
        for command, description in commands:
            sections.append(f"• <code>{command}</code> — {description}")
    return "\n".join(sections)


@router.message(Command("help"))
async def help_cmd(message: Message):
    await message.answer(
        "Motivi помогает с планированием, привычками, памятью, календарем и юзерботом.\n\n"
        "Используй /commands для полного списка команд.\n"
        "Если бот ждет ввод в каком-то сценарии, отправь /cancel."
    )


@router.message(Command("commands"))
async def commands_cmd(message: Message):
    await message.answer(_commands_text(), parse_mode="HTML")


@router.message()
async def fallback(message: Message):
    await message.answer(
        "Я здесь. Используй /commands для списка команд, /help для краткой справки "
        "или /cancel, если хочешь прервать текущее действие."
    )
