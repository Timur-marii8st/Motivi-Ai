from __future__ import annotations

from aiogram import Bot

_bot_instance: Bot | None = None


def set_bot_instance(bot: Bot | None) -> None:
    """Register (or clear) the process-wide aiogram Bot instance."""
    global _bot_instance
    _bot_instance = bot


def get_bot_instance() -> Bot:
    """Return the process-wide aiogram Bot instance."""
    if _bot_instance is None:
        raise RuntimeError("Bot instance is not initialized")
    return _bot_instance
