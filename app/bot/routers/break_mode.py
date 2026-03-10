from __future__ import annotations
from aiogram import Router, F
from aiogram.types import Message
from datetime import datetime, timezone, timedelta
from loguru import logger

from ...config import settings as app_settings
from ...services.profile_services import get_or_create_user
from ...services.settings_service import SettingsService

router = Router(name="break_mode")

@router.message(F.text.regexp(r"^/break"))
async def break_cmd(message: Message, session):
    """
    Activate break mode with duration.
    Usage: /break [1d|3d|1w|off]
    """
    parts = message.text.strip().split()
    
    user = await get_or_create_user(session, message.from_user.id, message.chat.id)
    settings = await SettingsService.get_or_create(session, user.id)
    
    if len(parts) == 1 or parts[1].lower() == "off":
        # Deactivate
        settings.break_mode_active = False
        settings.break_mode_until = None
        settings.touch()
        session.add(settings)
        await session.commit()

        if app_settings.is_feature_enabled("F011_BREAK_ENHANCED"):
            streak_msg = ""
            if app_settings.is_feature_enabled("F006_STREAKS") and user.streak_count > 0:
                streak_msg = (
                    f"\n🔥 Your streak survived thanks to break protection! "
                    f"Current streak: {user.streak_count} days."
                )
            await message.answer(
                f"🔔 Welcome back! I'm glad you're here.{streak_msg}\n\n"
                f"Let me know how you're doing and we'll get back on track together."
            )
        else:
            await message.answer("🔔 Режим перерыва отключен. Я возобновлю проактивные сообщения!")
        return
    
    # Parse duration
    duration_str = parts[1].lower()
    delta = None
    
    if duration_str.endswith("d"):
        days = int(duration_str[:-1])
        delta = timedelta(days=days)
    elif duration_str.endswith("w"):
        weeks = int(duration_str[:-1])
        delta = timedelta(weeks=weeks)
    elif duration_str.endswith("h"):
        hours = int(duration_str[:-1])
        delta = timedelta(hours=hours)
    else:
        await message.answer("Использование: /break [1d|3d|1w|off]\nПримеры: /break 1d, /break 1w, /break off")
        return
    
    until = datetime.now(timezone.utc) + delta
    
    settings.break_mode_active = True
    settings.break_mode_until = until
    settings.touch()
    session.add(settings)
    await session.commit()
    
    if app_settings.is_feature_enabled("F011_BREAK_ENHANCED"):
        # Freeze streak during break
        if app_settings.is_feature_enabled("F006_STREAKS"):
            try:
                from ...services.streak_service import StreakService
                await StreakService.freeze_streak_for_break(session, user)
            except Exception as e:
                logger.warning("Failed to freeze streak for user {}: {}", user.id, e)

        await message.answer(
            f"🔕 Taking a break is healthy. I'll keep your streaks frozen "
            f"and your memories safe until {until.strftime('%Y-%m-%d %H:%M UTC')}.\n\n"
            f"When you're ready, just say hi and I'll catch you up on everything. "
            f"Use /break off to come back anytime."
        )
    else:
        await message.answer(
            f"🔕 Режим перерыва активен до {until.strftime('%Y-%m-%d %H:%M UTC')}.\n"
            f"Я не буду отправлять проактивные сообщения до этого времени. "
            f"Используй /break off, чтобы возобновить когда угодно."
        )
    logger.info("User {} activated break mode until {}", user.id, until)

@router.message(F.text == "/export_data")
async def export_data_cmd(message: Message, session):
    """Export user data as JSON."""
    user = await get_or_create_user(session, message.from_user.id, message.chat.id)
    
    from ...services.account_service import AccountService
    import json
    import tempfile
    from aiogram.types import FSInputFile
    
    data = await AccountService.export_user_data(session, user.id)
    
    # Write to temp file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        temp_path = f.name
    
    # Send file
    doc = FSInputFile(temp_path, filename=f"motivi_data_{user.id}_{datetime.now(timezone.utc).strftime('%Y%m%d')}.json")
    await message.answer_document(doc, caption="📦 Полный экспорт твоих данных Motivi_AI (соответствует GDPR)")
    
    import os
    os.unlink(temp_path)
    
    logger.info("User {} exported their data", user.id)