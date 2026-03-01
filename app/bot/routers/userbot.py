"""
Userbot router — /connect_userbot, /disconnect_userbot, /userbot_interests.

This router manages the MTProto (Telethon) connection that lets the bot
monitor the user's personal Telegram account in read-only mode.

Authentication flow
-------------------
1. /connect_userbot
   - Checks that TELEGRAM_API_ID / TELEGRAM_API_HASH are configured.
   - If the user already has an active session → shows status.
   - Otherwise → asks for phone number (FSM: waiting_phone).

2. Phone received (FSM: waiting_phone)
   - Creates a Telethon client, calls send_code_request().
   - Stores the pending client + phone_code_hash in UserBotManager._pending.
   - Moves to FSM: waiting_code.

3. OTP code received (FSM: waiting_code)
   - Calls client.sign_in(). If 2FA is required, moves to waiting_password.
   - On success: saves StringSession to DB (encrypted), starts monitoring.

4. 2FA password received (FSM: waiting_password)
   - Calls client.sign_in(password=…).
   - On success: same as step 3.

Safety
------
* The user is instructed to use /cancel_userbot to abort the flow.
* Pending clients are cleaned up on cancellation and on error.
* Session strings are encrypted at rest via EncryptedTextType (Tink AES-GCM).
"""
from __future__ import annotations

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
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

from ...config import settings as app_settings
from ...services.userbot_manager import UserBotManager
from ...services.profile_services import get_or_create_user
from ..states import UserBotSetup

router = Router(name="userbot")


# ---------------------------------------------------------------------------
# /connect_userbot — entry point
# ---------------------------------------------------------------------------

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

    # Check for an existing active session
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
        "I'll monitor your channels and private messages in <b>read-only</b> mode:\n"
        "• Notify you about interesting channel posts\n"
        "• Suggest replies for incoming messages\n\n"
        "Your session is encrypted and stored securely. "
        "I will <b>never</b> send any message from your account.\n\n"
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
async def cmd_cancel_userbot(message: Message, state: FSMContext):
    user_id = message.from_user.id

    pending = UserBotManager.get_pending(user_id)
    if pending:
        try:
            await pending["client"].disconnect()
        except Exception:
            pass
        UserBotManager.clear_pending(user_id)

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

    # Clean up any leftover pending client
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
        # 2FA is enabled — ask for the cloud password
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

    # Delete the password message immediately for security
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

    # Stop and remove client
    await UserBotManager.stop_client(user.id)

    # Mark DB record as inactive
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
    """
    Usage: /userbot_interests technology, AI, startups, finance
    Sets the text used by the LLM to decide which channel posts to forward.
    """
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
    user_settings.userbot_channel_interests = text[:500]  # cap at 500 chars
    user_settings.touch()
    session.add(user_settings)
    await session.commit()

    await message.answer(
        f"✅ Interests saved: <i>{text[:200]}</i>\n\n"
        "I'll use this to filter which channel posts to notify you about.",
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

async def _finalize_connection(
    client: TelegramClient,
    user_id: int,
    message: Message,
    state: FSMContext,
    session,
    bot: Bot,
) -> None:
    """
    Save the authenticated session to the DB, start monitoring, and confirm.
    Called after a successful sign_in (either code or password path).
    """
    from sqlmodel import select
    from datetime import datetime, timezone
    from ...models.userbot_session import UserBotSession

    session_string = client.session.save()
    UserBotManager.clear_pending(user_id)

    # Upsert UserBotSession
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

    # Disconnect the temporary auth client and let the manager create a clean
    # monitoring client from the now-saved session string.
    try:
        await client.disconnect()
    except Exception:
        pass

    await UserBotManager.start_client(user_id=user_id, session_string=session_string, bot=bot)

    await state.clear()
    await message.answer(
        "✅ <b>Telegram account connected!</b>\n\n"
        "I'm now monitoring your account in read-only mode:\n"
        "• Interesting channel posts → I'll notify you\n"
        "• Incoming messages → I'll suggest replies\n\n"
        "Use <code>/userbot_interests topic1, topic2</code> to customise which "
        "channel posts I forward.\n"
        "Use /disconnect_userbot to stop monitoring at any time.",
        parse_mode="HTML",
    )
    logger.info("User {} successfully connected userbot", user_id)
