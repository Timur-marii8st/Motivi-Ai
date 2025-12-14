from __future__ import annotations
from aiogram import Router, F
from aiogram.types import Message

router = Router(name="common")

@router.message(F.text == "/help")
async def help_cmd(message: Message):
    await message.answer(
        "Привет, Я Мотиви! Я помогу тебе планировать день, следить за привычками и поддерживать мотивацию.\n"
        "Начни с /start. Настроив профиль, я буду вести утренние и вечерние чек-апы!"
    )

@router.message()
async def fallback(message: Message):
    await message.answer("Я здесь! Нажми /start, чтобы настроить твой профиль, или /help для дополнительной информации.")