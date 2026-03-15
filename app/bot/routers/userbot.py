"""
Userbot router — /connect_userbot, /disconnect_userbot, /userbot_interests,
plus callback handlers for reply approval (human-in-the-loop).

Authentication flow
-------------------
1. /connect_userbot → asks for phone number (FSM: waiting_phone).
2. Phone received → sends OTP → FSM: waiting_code.
3. OTP code → sign_in. If 2FA → FSM: waiting_password.
4. On success: saves StringSession to DB, starts monitoring.

Reply approval flow
-------------------
When the userbot monitor detects a relevant DM/group message, it sends
a notification with inline buttons: [✅ #1] [✅ #2] [✅ #3] [✏️ Edit] [🚫 Dismiss].
Pressing a button triggers a callback that:
  - "Send #N": fetches the pending reply from Redis, sends it via Telethon
    with human-like typing simulation and random delay.
  - "Edit": enters FSM waiting_text state for custom reply.
  - "Dismiss": deletes the pending reply from Redis and confirms.

Safety
------
* Replies are ONLY sent after explicit user approval (button press).
* Human-like delays (typing action + random pause) before sending.
* Rate-limited: max USERBOT_MAX_REPLIES_PER_DAY per user per day.
* Pending replies expire after USERBOT_REPLY_TIMEOUT seconds.
"""
from __future__ import annotations

import asyncio
import random

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger
from telethon import TelegramClient
from telethon.errors import (
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
    PasswordHashInvalidError,
    PhoneNumberInvalidError,
    FloodWaitError,
)
from telethon.sessions import StringSession
from telethon.tl.functions.messages import SetTypingRequest
from telethon.tl.types import SendMessageTypingAction

from ...config import settings as app_settings
from ...services.userbot_manager import UserBotManager
from ...services.userbot_monitor import (
    check_reply_rate_limit,
    delete_pending_reply,
    get_pending_reply,
    increment_reply_counter,
    mark_bot_sent_reply,
)
from ...services.profile_services import get_or_create_user
from ..states import UserBotSetup, UserBotReplyEdit

router = Router(name="userbot")


# ===========================================================================
# Reply approval callbacks
# ===========================================================================

@router.callback_query(F.data.startswith("ub_send:"))
async def cb_approve_reply(callback: CallbackQuery, session):
    """User approved sending a suggested reply."""
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("❌ Invalid action")
        return

    pending_key = parts[1]
    try:
        suggestion_idx = int(parts[2])
    except (ValueError, IndexError):
        await callback.answer("❌ Invalid action")
        return

    user = await get_or_create_user(session, callback.from_user.id, callback.message.chat.id)
    pending = await get_pending_reply(pending_key)

    if not pending:
        await callback.answer("⏰ This reply has expired.", show_alert=True)
        await _mark_message_expired(callback)
        return

    if pending["user_id"] != user.id:
        await callback.answer("❌ Not your reply.", show_alert=True)
        return

    if suggestion_idx < 0 or suggestion_idx >= len(pending["suggestions"]):
        await callback.answer("❌ Invalid suggestion index.", show_alert=True)
        return

    # Rate limit check
    if not await check_reply_rate_limit(user.id):
        await callback.answer(
            f"⚠️ Daily reply limit reached ({app_settings.USERBOT_MAX_REPLIES_PER_DAY}/day).",
            show_alert=True,
        )
        return

    reply_text = pending["suggestions"][suggestion_idx]
    success = await _send_reply_with_human_simulation(
        user_id=user.id,
        chat_id=pending["chat_id"],
        reply_to_msg_id=pending["message_id"],
        text=reply_text,
    )

    await delete_pending_reply(pending_key)

    if success:
        await increment_reply_counter(user.id)
        await callback.answer("✅ Reply sent!")
        await callback.message.edit_text(
            callback.message.text + "\n\n✅ <b>Sent:</b> " + _esc(reply_text),
            parse_mode="HTML",
            reply_markup=None,
        )
    else:
        await callback.answer("❌ Failed to send. Session may be expired.", show_alert=True)
        await callback.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data.startswith("ub_edit:"))
async def cb_edit_reply(callback: CallbackQuery, state: FSMContext, session):
    """User wants to type a custom reply."""
    parts = callback.data.split(":")
    if len(parts) != 2:
        await callback.answer("❌ Invalid action")
        return

    pending_key = parts[1]
    user = await get_or_create_user(session, callback.from_user.id, callback.message.chat.id)
    pending = await get_pending_reply(pending_key)

    if not pending:
        await callback.answer("⏰ This reply has expired.", show_alert=True)
        await _mark_message_expired(callback)
        return

    if pending["user_id"] != user.id:
        await callback.answer("❌ Not your reply.", show_alert=True)
        return

    # Store pending_key in FSM state for the text handler
    await state.set_state(UserBotReplyEdit.waiting_text)
    await state.update_data(pending_key=pending_key, notification_msg_id=callback.message.message_id)

    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"✏️ Type your reply to <b>{_esc(pending['sender_name'])}</b>.\n"
        "Send /cancel_reply to abort.",
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("ub_dismiss:"))
async def cb_dismiss_reply(callback: CallbackQuery, session):
    """User dismissed the reply suggestion."""
    parts = callback.data.split(":")
    if len(parts) != 2:
        await callback.answer("❌ Invalid action")
        return

    pending_key = parts[1]
    user = await get_or_create_user(session, callback.from_user.id, callback.message.chat.id)
    pending = await get_pending_reply(pending_key)

    if pending and pending["user_id"] != user.id:
        await callback.answer("❌ Not your reply.", show_alert=True)
        return

    await delete_pending_reply(pending_key)
    await callback.answer("🚫 Dismissed")
    await callback.message.edit_text(
        callback.message.text + "\n\n🚫 <i>Dismissed</i>",
        parse_mode="HTML",
        reply_markup=None,
    )


# ---------------------------------------------------------------------------
# FSM: custom reply text input
# ---------------------------------------------------------------------------

@router.message(Command("cancel_reply"))
async def cmd_cancel_reply(message: Message, state: FSMContext):
    """Cancel the custom reply editing flow."""
    data = await state.get_data()
    pending_key = data.get("pending_key")
    if pending_key:
        await delete_pending_reply(pending_key)
    await state.clear()
    await message.answer("❌ Reply cancelled.")


@router.message(UserBotReplyEdit.waiting_text)
async def process_custom_reply(message: Message, state: FSMContext, session, bot: Bot):
    """Handle the user's custom reply text."""
    custom_text = (message.text or "").strip()
    if not custom_text:
        await message.answer("Please type a reply or send /cancel_reply to abort.")
        return

    data = await state.get_data()
    pending_key = data.get("pending_key")
    if not pending_key:
        await state.clear()
        await message.answer("⚠️ Session lost. Please try again from the notification.")
        return

    user = await get_or_create_user(session, message.from_user.id, message.chat.id)
    pending = await get_pending_reply(pending_key)

    if not pending:
        await state.clear()
        await message.answer("⏰ This reply has expired.")
        return

    if pending["user_id"] != user.id:
        await state.clear()
        await message.answer("❌ Not your reply.")
        return

    # Rate limit
    if not await check_reply_rate_limit(user.id):
        await state.clear()
        await message.answer(
            f"⚠️ Daily reply limit reached ({app_settings.USERBOT_MAX_REPLIES_PER_DAY}/day)."
        )
        return

    success = await _send_reply_with_human_simulation(
        user_id=user.id,
        chat_id=pending["chat_id"],
        reply_to_msg_id=pending["message_id"],
        text=custom_text,
    )

    await delete_pending_reply(pending_key)
    await state.clear()

    if success:
        await increment_reply_counter(user.id)
        await message.answer(
            f"✅ <b>Reply sent to {_esc(pending['sender_name'])}:</b>\n"
            f"<i>{_esc(custom_text[:200])}</i>",
            parse_mode="HTML",
        )
    else:
        await message.answer("❌ Failed to send. Your Telethon session may have expired.")


# ===========================================================================
# Human-like reply sending
# ===========================================================================

async def _send_reply_with_human_simulation(
    *,
    user_id: int,
    chat_id: int,
    reply_to_msg_id: int,
    text: str,
) -> bool:
    """
    Send a reply via Telethon with human-like typing simulation.

    1. Show "typing..." action in the target chat
    2. Wait a random delay proportional to text length
    3. Send the message as a reply to the original

    Returns True on success, False on failure.
    """
    client = UserBotManager.get_client(user_id)
    if not client:
        logger.warning("No active Telethon client for user {} — cannot send reply", user_id)
        return False

    try:
        # 1. Send typing action
        try:
            await client(SetTypingRequest(
                peer=chat_id,
                action=SendMessageTypingAction(),
            ))
        except Exception as exc:
            logger.debug("Could not send typing action for user {}: {}", user_id, exc)

        # 2. Human-like delay: base + proportional to text length
        base_delay = random.uniform(
            app_settings.USERBOT_TYPING_DELAY_MIN,
            app_settings.USERBOT_TYPING_DELAY_MAX,
        )
        # ~50ms per character, capped at 5 extra seconds
        char_delay = min(len(text) * 0.05, 5.0)
        total_delay = base_delay + char_delay
        await asyncio.sleep(total_delay)

        # 3. Mark as bot-sent so the outgoing handler skips it
        await mark_bot_sent_reply(user_id, chat_id)

        # 4. Send the message as a reply
        await client.send_message(
            entity=chat_id,
            message=text,
            reply_to=reply_to_msg_id,
        )

        logger.info(
            "Userbot: sent approved reply for user {} to chat {} (delay={:.1f}s)",
            user_id, chat_id, total_delay,
        )
        return True

    except Exception as exc:
        logger.error(
            "Userbot: failed to send reply for user {} to chat {}: {}",
            user_id, chat_id, exc,
        )
        return False


# ===========================================================================
# /connect_userbot — entry point
# ===========================================================================

@router.message(Command("connect_userbot"))
async def cmd_connect_userbot(message: Message, state: FSMContext, session, bot: Bot):
    if not app_settings.TELEGRAM_API_ID or not app_settings.TELEGRAM_API_HASH:
        await message.answer(
            "⚠️ Userbot is not configured on this server.\n"
            "The admin needs to set <code>TELEGRAM_API_ID</code> and "
            "<code>TELEGRAM_API_HASH</code> in the environment.",
            parse_mode="HTML",
        )
        return

    user = await get_or_create_user(session, message.from_user.id, message.chat.id)

    from sqlmodel import select
    from ...models.userbot_session import UserBotSession

    result = await session.execute(
        select(UserBotSession).where(
            UserBotSession.user_id == user.id,
            UserBotSession.is_active == True,  # noqa: E712
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        client = UserBotManager.get_client(user.id)
        status = "🟢 connected and monitoring" if client else "🔴 session saved but client not running"
        await message.answer(
            f"Your personal Telegram account is already linked ({status}).\n\n"
            f"Use /disconnect_userbot to remove the connection.",
        )
        return

    await message.answer(
        "🔐 <b>Connect your Telegram account</b>\n\n"
        "I'll monitor your channels, groups, and private messages:\n"
        "• Notify you about interesting channel posts\n"
        "• Suggest replies for incoming messages\n"
        "• Send replies <b>only after your approval</b> 👆\n\n"
        "Your session is encrypted and stored securely.\n\n"
        "Please send your phone number in international format "
        "(e.g. <code>+79001234567</code>).\n\n"
        "Send /cancel_userbot to abort.",
        parse_mode="HTML",
    )
    await state.set_state(UserBotSetup.waiting_phone)


# ---------------------------------------------------------------------------
# /cancel_userbot — abort the setup at any step
# ---------------------------------------------------------------------------

@router.message(Command("cancel_userbot"))
async def cmd_cancel_userbot(message: Message, state: FSMContext, session):
    user = await get_or_create_user(session, message.from_user.id, message.chat.id)

    pending = UserBotManager.get_pending(user.id)
    if pending:
        try:
            await pending["client"].disconnect()
        except Exception:
            pass
        UserBotManager.clear_pending(user.id)

    await state.clear()
    await message.answer("❌ Userbot setup cancelled.")


# ---------------------------------------------------------------------------
# Step 1 — phone number
# ---------------------------------------------------------------------------

@router.message(UserBotSetup.waiting_phone)
async def process_phone(message: Message, state: FSMContext, session, bot: Bot):
    phone = (message.text or "").strip()
    if not phone.startswith("+"):
        await message.answer(
            "Please use international format starting with +, e.g. <code>+79001234567</code>",
            parse_mode="HTML",
        )
        return

    user = await get_or_create_user(session, message.from_user.id, message.chat.id)

    old = UserBotManager.get_pending(user.id)
    if old:
        try:
            await old["client"].disconnect()
        except Exception:
            pass

    wait_msg = await message.answer("📱 Sending verification code…")

    try:
        client = TelegramClient(
            StringSession(),
            app_settings.TELEGRAM_API_ID,
            app_settings.TELEGRAM_API_HASH,
        )
        await client.connect()
        sent = await client.send_code_request(phone)
    except PhoneNumberInvalidError:
        await wait_msg.edit_text("❌ Invalid phone number. Please try again.")
        return
    except FloodWaitError as e:
        await wait_msg.edit_text(
            f"⏳ Too many requests. Please wait {e.seconds}s and try again."
        )
        return
    except Exception as exc:
        logger.error("Userbot send_code_request failed for user {}: {}", user.id, exc)
        await wait_msg.edit_text("❌ Failed to send code. Please try again later.")
        return

    UserBotManager.set_pending(
        user.id,
        {
            "client": client,
            "phone": phone,
            "phone_code_hash": sent.phone_code_hash,
        },
    )

    await wait_msg.edit_text(
        "✅ A verification code has been sent to your Telegram account.\n\n"
        "Please send the code here (e.g. <code>12345</code>).\n"
        "Send /cancel_userbot to abort.",
        parse_mode="HTML",
    )
    await state.set_state(UserBotSetup.waiting_code)


# ---------------------------------------------------------------------------
# Step 2 — OTP code
# ---------------------------------------------------------------------------

@router.message(UserBotSetup.waiting_code)
async def process_code(message: Message, state: FSMContext, session, bot: Bot):
    code = (message.text or "").strip().replace(" ", "")
    user = await get_or_create_user(session, message.from_user.id, message.chat.id)

    pending = UserBotManager.get_pending(user.id)
    if not pending:
        await message.answer("⚠️ Session expired. Please start over with /connect_userbot.")
        await state.clear()
        return

    client: TelegramClient = pending["client"]
    phone: str = pending["phone"]
    phone_code_hash: str = pending["phone_code_hash"]

    try:
        await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
    except SessionPasswordNeededError:
        await message.answer(
            "🔒 Two-factor authentication is enabled.\n"
            "Please send your <b>cloud password</b>.\n"
            "Send /cancel_userbot to abort.",
            parse_mode="HTML",
        )
        await state.set_state(UserBotSetup.waiting_password)
        return
    except PhoneCodeInvalidError:
        await message.answer("❌ Invalid code. Please try again.")
        return
    except PhoneCodeExpiredError:
        UserBotManager.clear_pending(user.id)
        try:
            await client.disconnect()
        except Exception:
            pass
        await state.clear()
        await message.answer(
            "❌ The code has expired. Please start over with /connect_userbot."
        )
        return
    except Exception as exc:
        logger.error("Userbot sign_in (code) failed for user {}: {}", user.id, exc)
        await message.answer("❌ Sign-in failed. Please try again later.")
        return

    await _finalize_connection(client, user.id, message, state, session, bot)


# ---------------------------------------------------------------------------
# Step 3 — 2FA cloud password
# ---------------------------------------------------------------------------

@router.message(UserBotSetup.waiting_password)
async def process_password(message: Message, state: FSMContext, session, bot: Bot):
    password = message.text or ""
    user = await get_or_create_user(session, message.from_user.id, message.chat.id)

    pending = UserBotManager.get_pending(user.id)
    if not pending:
        await message.answer("⚠️ Session expired. Please start over with /connect_userbot.")
        await state.clear()
        return

    client: TelegramClient = pending["client"]

    try:
        await client.sign_in(password=password)
    except PasswordHashInvalidError:
        await message.answer("❌ Wrong password. Please try again.")
        return
    except Exception as exc:
        logger.error("Userbot sign_in (password) failed for user {}: {}", user.id, exc)
        await message.answer("❌ Sign-in failed. Please try again later.")
        return

    try:
        await message.delete()
    except Exception:
        pass

    await _finalize_connection(client, user.id, message, state, session, bot)


# ---------------------------------------------------------------------------
# /disconnect_userbot
# ---------------------------------------------------------------------------

@router.message(Command("disconnect_userbot"))
async def cmd_disconnect_userbot(message: Message, state: FSMContext, session, bot: Bot):
    user = await get_or_create_user(session, message.from_user.id, message.chat.id)

    from sqlmodel import select
    from ...models.userbot_session import UserBotSession

    result = await session.execute(
        select(UserBotSession).where(UserBotSession.user_id == user.id)
    )
    ubot_session = result.scalar_one_or_none()

    if not ubot_session:
        await message.answer("You don't have a connected Telegram account.")
        return

    await UserBotManager.stop_client(user.id)

    ubot_session.is_active = False
    ubot_session.session_string = None
    ubot_session.touch()
    session.add(ubot_session)
    await session.commit()

    await message.answer(
        "✅ Your Telegram account has been disconnected.\n"
        "No more monitoring will take place."
    )
    logger.info("User {} disconnected userbot", user.id)


# ---------------------------------------------------------------------------
# /userbot_interests — set interest description for channel filtering
# ---------------------------------------------------------------------------

@router.message(Command("userbot_interests"))
async def cmd_userbot_interests(message: Message, session):
    user = await get_or_create_user(session, message.from_user.id, message.chat.id)

    text = (message.text or "").removeprefix("/userbot_interests").strip()
    if not text:
        await message.answer(
            "📝 Tell me what topics interest you so I can filter channel posts.\n\n"
            "Example:\n"
            "<code>/userbot_interests technology, AI, startups, finance, science</code>",
            parse_mode="HTML",
        )
        return

    from ...services.settings_service import SettingsService

    user_settings = await SettingsService.get_or_create(session, user.id)
    user_settings.userbot_channel_interests = text[:500]
    user_settings.touch()
    session.add(user_settings)
    await session.commit()

    await message.answer(
        f"✅ Interests saved: <i>{text[:200]}</i>\n\n"
        "I'll use this to filter which channel posts to notify you about.",
        parse_mode="HTML",
    )


# ===========================================================================
# Internal helpers
# ===========================================================================

async def _finalize_connection(
    client: TelegramClient,
    user_id: int,
    message: Message,
    state: FSMContext,
    session,
    bot: Bot,
) -> None:
    """Save the authenticated session to the DB, start monitoring, and confirm."""
    from sqlmodel import select
    from ...models.userbot_session import UserBotSession

    session_string = client.session.save()
    UserBotManager.clear_pending(user_id)

    result = await session.execute(
        select(UserBotSession).where(UserBotSession.user_id == user_id)
    )
    ubot_session = result.scalar_one_or_none()
    if ubot_session:
        ubot_session.session_string = session_string
        ubot_session.is_active = True
        ubot_session.touch()
    else:
        ubot_session = UserBotSession(
            user_id=user_id,
            session_string=session_string,
            is_active=True,
        )
    session.add(ubot_session)
    await session.commit()

    try:
        await client.disconnect()
    except Exception:
        pass

    await UserBotManager.start_client(user_id=user_id, session_string=session_string, bot=bot)

    await state.clear()
    await message.answer(
        "✅ <b>Telegram account connected!</b>\n\n"
        "I'm now monitoring your account:\n"
        "• Interesting channel posts → notifications\n"
        "• Incoming DMs → reply suggestions with approval buttons\n"
        "• Group mentions/replies → reply suggestions with approval buttons\n\n"
        "I will <b>only send replies after your approval</b> 👆\n\n"
        "Use <code>/userbot_interests topic1, topic2</code> to customise channel filters.\n"
        "Use /disconnect_userbot to stop monitoring at any time.",
        parse_mode="HTML",
    )
    logger.info("User {} successfully connected userbot", user_id)


async def _mark_message_expired(callback: CallbackQuery) -> None:
    """Update the notification message to show it's expired."""
    try:
        await callback.message.edit_text(
            callback.message.text + "\n\n⏰ <i>Expired</i>",
            parse_mode="HTML",
            reply_markup=None,
        )
    except Exception:
        pass


def _esc(text: str) -> str:
    """Escape HTML special characters for Telegram HTML parse mode."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
