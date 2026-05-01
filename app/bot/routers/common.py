from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message

router = Router(name="common")


@router.message(F.text == "/help")
async def help_cmd(message: Message):
    await message.answer(
        "Привет, я Motivi. Помогаю планировать, держать контекст, работать с привычками "
        "и иногда аккуратно возвращать к важным вещам.\n"
        "Начни с /start. Проактивные сообщения можно настроить через /settings."
    )


@router.message()
async def fallback(message: Message):
    await message.answer(
        "Я здесь. Нажми /start, чтобы настроить профиль, или /help для короткой справки."
    )
