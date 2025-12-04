from __future__ import annotations
from aiogram import Router, F
from aiogram.types import Message

router = Router(name="common")

@router.message(F.text == "/help")
async def help_cmd(message: Message):
    await message.answer(
        "I’m Motivi! I help plan your day, track habits, and keep you motivated.\n"
        "Try /start to onboard. Once set up, I’ll do morning and evening check-ins!"
    )

@router.message()
async def fallback(message: Message):
    await message.answer("I’m here! Use /start to set up your profile, or /help to learn more.")