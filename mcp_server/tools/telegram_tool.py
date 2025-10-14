from __future__ import annotations
from pathlib import Path
from aiogram import Bot
from aiogram.types import FSInputFile
from loguru import logger

from ..config import mcp_settings

bot = Bot(token=mcp_settings.TELEGRAM_BOT_TOKEN)

async def send_file(chat_id: int, file_path: str, caption: str | None = None) -> int:
    """
    Send a file to a Telegram chat. Returns message_id.
    """
    path = Path(file_path).resolve()
    allowed_dir = Path(mcp_settings.TEMP_FILES_DIR).resolve()
    if not str(path).startswith(str(allowed_dir)) or not path.exists():
        logger.security(f"Blocked attempt to send unauthorized file: {file_path}")
        raise FileNotFoundError(f"File not found or access denied.")
    
    input_file = FSInputFile(path)
    message = await bot.send_document(chat_id=chat_id, document=input_file, caption=caption)
    logger.info("Sent file to chat {}: message_id={}", chat_id, message.message_id)
    return message.message_id

async def send_telegram_message_and_pin(chat_id: int, message: str, disable_notification: bool = True):
    """
    Send and pin a message in a Telegram chat.
    """
    sent_message = await bot.send_message(chat_id=chat_id, text=message, disable_notification=disable_notification)
    message_id = sent_message.message_id
    await bot.pin_chat_message(
        chat_id=chat_id,
        message_id=message_id,
        disable_notification=disable_notification,
    )

    logger.info("send and inned message {} in chat {}", message_id, chat_id)