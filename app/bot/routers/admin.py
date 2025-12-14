from __future__ import annotations
from aiogram import Router, F
from aiogram.types import Message
from aiogram import Bot
from sqlmodel import select, func
from loguru import logger

from ...models.users import User
from ...models.episode import Episode
from ...config import settings


router = Router(name="admin")

# Whitelist admin user IDs (set in .env or config)
ADMIN_IDS_STR = settings.ADMIN_USER_IDS or ""
ADMIN_USER_IDS = {int(uid.strip()) for uid in ADMIN_IDS_STR.split(',') if uid.strip()}

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_USER_IDS

@router.message(F.text == "/admin_stats")
async def admin_stats(message: Message, session):
    """Show system statistics (admin only)."""
    if not is_admin(message.from_user.id):
        return
    
    # Total users
    user_count_result = await session.execute(select(func.count(User.id)))
    user_count = user_count_result.scalar_one()
    
    # Total episodes
    episode_count_result = await session.execute(select(func.count(Episode.id)))
    episode_count = episode_count_result.scalar_one()
    
    # Active users (interacted in last 7 days)
    from datetime import datetime, timezone, timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    active_result = await session.execute(
        select(func.count(User.id)).where(User.updated_at >= cutoff)
    )
    active_count = active_result.scalar_one()
    
    text = (
        f"<b>📋 Статистика Motivi_AI</b>\n\n"
        f"Всего пользователей: {user_count}\n"
        f"Активных (7 дней): {active_count}\n"
        f"Всего эпизодов: {episode_count}\n"
    )
    
    await message.answer(text)
    logger.info("Admin {} viewed stats", message.from_user.id)

@router.message(F.text.startswith("/admin_broadcast"))
async def admin_broadcast(message: Message, session, bot: Bot):
    """Broadcast message to all users (admin only)."""
    if not is_admin(message.from_user.id):
        return
    
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /admin_broadcast <сообщение>")
        return
    
    broadcast_msg = parts[1]
    
    result = await session.execute(select(User))
    users = result.scalars().all()
    
    sent = 0
    failed = 0
    
    for user in users:
        try:
            await bot.send_message(user.tg_chat_id, f"📢 <b>Объявление:</b>\n\n{broadcast_msg}")
            sent += 1
        except Exception as e:
            logger.error("Broadcast failed for user {}: {}", user.id, e)
            failed += 1
    
    await message.answer(f"✅ Объявление отправлено {sent} пользователям. Ошибок: {failed}")
    logger.warning("Admin {} broadcast to {} users", message.from_user.id, sent)