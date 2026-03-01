from __future__ import annotations
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from loguru import logger

from ...services.profile_services import get_or_create_user
from ...services.settings_service import SettingsService
from ...scheduler.job_manager import JobManager
from ...config import settings as app_settings

router = Router(name="settings")

@router.message(F.text == "/settings")
async def settings_cmd(message: Message, session):
    """Display settings with toggles."""
    user = await get_or_create_user(session, message.from_user.id, message.chat.id)
    settings = await SettingsService.get_or_create(session, user.id)
    
    text = (
        f"<b>⚙️ Settings</b>\n\n"
        f"<b>Proactive Features:</b>\n"
        f"• Morning check-in: {'✅ Enabled' if settings.enable_morning_checkin else '❌ Disabled'}\n"
        f"• Evening wrap-up: {'✅ Enabled' if settings.enable_evening_wrapup else '❌ Disabled'}\n"
        f"• Weekly plan: {'✅ Enabled' if settings.enable_weekly_plan else '❌ Disabled'}\n"
        f"• Monthly plan: {'✅ Enabled' if settings.enable_monthly_plan else '❌ Disabled'}\n"
        f"• News digest: {'✅ Enabled' if settings.enable_news_digest else '❌ Disabled'} "
        f"(fires {app_settings.NEWS_DIGEST_OFFSET_MINUTES} min after wake time)\n\n"
        f"<b>Break Mode:</b>\n"
        f"• Status: {'🔕 Active' if settings.break_mode_active else '🔔 Inactive'}\n"
        f"• Until: {settings.break_mode_until.strftime('%Y-%m-%d %H:%M') if settings.break_mode_until else 'N/A'}\n\n"
        f"<b>User Bot (personal account monitoring):</b>\n"
        f"• Channel monitoring: {'✅ Enabled' if settings.enable_channel_monitoring else '❌ Disabled'}\n"
        f"• DM notifications: {'✅ Enabled' if settings.enable_dm_notifications else '❌ Disabled'}\n"
        f"• Interests: <i>{settings.userbot_channel_interests or 'not set — use /userbot_interests'}</i>\n"
        f"• Connect: /connect_userbot  |  Disconnect: /disconnect_userbot\n"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{'✅' if settings.enable_morning_checkin else '❌'} Morning Check-in",
            callback_data="settings_toggle_morning"
        )],
        [InlineKeyboardButton(
            text=f"{'✅' if settings.enable_evening_wrapup else '❌'} Evening Wrap-up",
            callback_data="settings_toggle_evening"
        )],
        [InlineKeyboardButton(
            text=f"{'✅' if settings.enable_weekly_plan else '❌'} Weekly Plan",
            callback_data="settings_toggle_weekly"
        )],
        [InlineKeyboardButton(
            text=f"{'✅' if settings.enable_monthly_plan else '❌'} Monthly Plan",
            callback_data="settings_toggle_monthly"
        )],
        [InlineKeyboardButton(
            text=f"{'✅' if settings.enable_news_digest else '❌'} News Digest",
            callback_data="settings_toggle_news_digest"
        )],
        [InlineKeyboardButton(
            text=f"{'✅' if settings.enable_channel_monitoring else '❌'} Channel Monitoring",
            callback_data="settings_toggle_channel_monitoring"
        )],
        [InlineKeyboardButton(
            text=f"{'✅' if settings.enable_dm_notifications else '❌'} DM Notifications",
            callback_data="settings_toggle_dm_notifications"
        )],
    ])
    
    await message.answer(text, reply_markup=keyboard)

@router.callback_query(F.data.startswith("settings_toggle_"))
async def toggle_setting(callback: CallbackQuery, session):
    user = await get_or_create_user(session, callback.from_user.id, callback.message.chat.id)
    settings = await SettingsService.get_or_create(session, user.id)
    
    setting = callback.data.replace("settings_toggle_", "")
    
    if setting == "morning":
        settings.enable_morning_checkin = not settings.enable_morning_checkin
    elif setting == "evening":
        settings.enable_evening_wrapup = not settings.enable_evening_wrapup
    elif setting == "weekly":
        settings.enable_weekly_plan = not settings.enable_weekly_plan
    elif setting == "monthly":
        settings.enable_monthly_plan = not settings.enable_monthly_plan
    elif setting == "news_digest":
        settings.enable_news_digest = not settings.enable_news_digest
    elif setting == "channel_monitoring":
        settings.enable_channel_monitoring = not settings.enable_channel_monitoring
    elif setting == "dm_notifications":
        settings.enable_dm_notifications = not settings.enable_dm_notifications

    settings.touch()
    session.add(settings)
    await session.commit()
    
    # Reschedule jobs
    JobManager.schedule_user_jobs(user, settings)
    
    await callback.answer(f"✅ Setting updated")
    
    # Refresh settings display
    await settings_cmd(callback.message, session)