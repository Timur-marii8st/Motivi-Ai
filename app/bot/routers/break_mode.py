from __future__ import annotations
from aiogram import Router, F
from aiogram.types import Message
from datetime import datetime, timedelta
from loguru import logger

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
        
        await message.answer("🔔 Break mode deactivated. I'll resume proactive messages!")
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
        await message.answer("Usage: /break [1d|3d|1w|off]\nExamples: /break 1d, /break 1w, /break off")
        return
    
    until = datetime.utcnow() + delta
    
    settings.break_mode_active = True
    settings.break_mode_until = until
    settings.touch()
    session.add(settings)
    await session.commit()
    
    await message.answer(
        f"🔕 Break mode activated until {until.strftime('%Y-%m-%d %H:%M UTC')}.\n"
        f"I won't send proactive messages until then. Use /break off to resume anytime."
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
    doc = FSInputFile(temp_path, filename=f"motivi_data_{user.id}_{datetime.utcnow().strftime('%Y%m%d')}.json")
    await message.answer_document(doc, caption="📦 Your complete Motivi_AI data export (GDPR compliant)")
    
    import os
    os.unlink(temp_path)
    
    logger.info("User {} exported their data", user.id)