from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ...config import settings as app_settings
from ...scheduler.job_manager import JobManager
from ...services.profile_services import get_or_create_user
from ...services.settings_service import SettingsService

router = Router(name="settings")


def _status(enabled: bool) -> str:
    return "✅ Enabled" if enabled else "❌ Disabled"


def _button_status(enabled: bool) -> str:
    return "✅" if enabled else "❌"


@router.message(F.text == "/settings")
async def settings_cmd(message: Message, session):
    """Display settings with toggles."""
    user = await get_or_create_user(session, message.from_user.id, message.chat.id)
    user_settings = await SettingsService.get_or_create(session, user.id)

    text = (
        "<b>⚙️ Settings</b>\n\n"
        "<b>Proactivity:</b>\n"
        f"• Smart proactive messages: {_status(user_settings.enable_smart_proactivity)}\n"
        f"• Max proactive messages/day: <b>{user_settings.proactive_max_messages_per_day}</b>\n"
        f"• News digest: {_status(user_settings.enable_news_digest)} "
        f"(fires {app_settings.NEWS_DIGEST_OFFSET_MINUTES} min after wake time)\n\n"
        "<b>Break Mode:</b>\n"
        f"• Status: {'🔕 Active' if user_settings.break_mode_active else '🔔 Inactive'}\n"
        f"• Until: {user_settings.break_mode_until.strftime('%Y-%m-%d %H:%M') if user_settings.break_mode_until else 'N/A'}\n\n"
        "<b>User Bot (personal account monitoring):</b>\n"
        f"• Channel monitoring: {_status(user_settings.enable_channel_monitoring)}\n"
        f"• DM notifications: {_status(user_settings.enable_dm_notifications)}\n"
        f"• Group monitoring: {_status(user_settings.enable_group_monitoring)}\n"
        f"• Reply approval: {_status(user_settings.enable_reply_approval)}\n"
        f"• Interests: <i>{user_settings.userbot_channel_interests or 'not set — use /userbot_interests'}</i>\n"
        "• Connect: /connect_userbot  |  Disconnect: /disconnect_userbot\n"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{_button_status(user_settings.enable_smart_proactivity)} Smart Proactivity",
                    callback_data="settings_toggle_smart_proactivity",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"Max/day: {user_settings.proactive_max_messages_per_day}",
                    callback_data="settings_cycle_proactive_max",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{_button_status(user_settings.enable_news_digest)} News Digest",
                    callback_data="settings_toggle_news_digest",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{_button_status(user_settings.enable_channel_monitoring)} Channel Monitoring",
                    callback_data="settings_toggle_channel_monitoring",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{_button_status(user_settings.enable_dm_notifications)} DM Notifications",
                    callback_data="settings_toggle_dm_notifications",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{_button_status(user_settings.enable_group_monitoring)} Group Monitoring",
                    callback_data="settings_toggle_group_monitoring",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{_button_status(user_settings.enable_reply_approval)} Reply Approval",
                    callback_data="settings_toggle_reply_approval",
                )
            ],
        ]
    )

    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("settings_toggle_"))
async def toggle_setting(callback: CallbackQuery, session):
    user = await get_or_create_user(session, callback.from_user.id, callback.message.chat.id)
    user_settings = await SettingsService.get_or_create(session, user.id)

    setting = callback.data.replace("settings_toggle_", "")

    if setting == "smart_proactivity":
        user_settings.enable_smart_proactivity = not user_settings.enable_smart_proactivity
    elif setting == "news_digest":
        user_settings.enable_news_digest = not user_settings.enable_news_digest
    elif setting == "channel_monitoring":
        user_settings.enable_channel_monitoring = not user_settings.enable_channel_monitoring
    elif setting == "dm_notifications":
        user_settings.enable_dm_notifications = not user_settings.enable_dm_notifications
    elif setting == "group_monitoring":
        user_settings.enable_group_monitoring = not user_settings.enable_group_monitoring
    elif setting == "reply_approval":
        user_settings.enable_reply_approval = not user_settings.enable_reply_approval

    user_settings.touch()
    session.add(user_settings)
    await session.commit()

    JobManager.schedule_user_jobs(user, user_settings)

    await callback.answer("✅ Setting updated")
    await settings_cmd(callback.message, session)


@router.callback_query(F.data == "settings_cycle_proactive_max")
async def cycle_proactive_max(callback: CallbackQuery, session):
    user = await get_or_create_user(session, callback.from_user.id, callback.message.chat.id)
    user_settings = await SettingsService.get_or_create(session, user.id)

    current = user_settings.proactive_max_messages_per_day or 1
    user_settings.proactive_max_messages_per_day = {0: 1, 1: 2, 2: 3, 3: 0}.get(current, 1)
    user_settings.touch()
    session.add(user_settings)
    await session.commit()

    JobManager.schedule_user_jobs(user, user_settings)

    await callback.answer("✅ Setting updated")
    await settings_cmd(callback.message, session)
