"""
Userbot router — /connect_userbot, /disconnect_userbot, /userbot_interests.

Authentication flow
-------------------
1. /connect_userbot → shows a QR login link (Telegram Desktop device link).
2. QR confirmed → sign_in. If 2FA → FSM: waiting_password.
3. On success: saves StringSession to DB, starts monitoring.

The connected account is monitored READ-ONLY: Motivi notifies about important
messages and channel posts, and fills her internal calendar from them. She
never sends messages on behalf of the user.
"""

from __future__ import annotations

import asyncio
from io import BytesIO

from aiogram import Router, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from loguru import logger
import qrcode
from telethon import TelegramClient
from telethon.errors import (
    SessionPasswordNeededError,
    PasswordHashInvalidError,
)
from telethon.sessions import StringSession

from ...config import settings as app_settings
from ...services.userbot_manager import UserBotManager
from ...services.profile_services import get_or_create_user
from ...utils.telegram_mtproto import build_telethon_proxy
from ..states import UserBotSetup

router = Router(name="userbot")


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
        is_alive = False
        if client:
            try:
                is_alive = await client.is_connected()
            except Exception:
                pass

        if is_alive:
            await message.answer(
                "Your personal Telegram account is already linked (🟢 connected and monitoring).\n\n"
                "Use /disconnect_userbot to remove the connection.",
            )
            return

        restart_msg = await message.answer(
            "🔴 Session saved but client not running. Restarting…"
        )
        await UserBotManager.stop_client(user.id)
        await UserBotManager.start_client(user.id, existing.session_string or "", bot)

        restarted = UserBotManager.get_client(user.id)
        restarted_alive = False
        if restarted:
            try:
                restarted_alive = await restarted.is_connected()
            except Exception:
                pass

        if restarted_alive:
            await restart_msg.edit_text("✅ Userbot restarted and monitoring.")
        else:
            await restart_msg.edit_text(
                "❌ Failed to restart the userbot.\n"
                "Try /disconnect_userbot first, then /connect_userbot again."
            )
        return

    old = UserBotManager.get_pending(user.id)
    if old:
        try:
            await old["client"].disconnect()
        except Exception:
            pass
        UserBotManager.clear_pending(user.id)

    wait_msg = await message.answer("🔐 Preparing secure Telegram login…")

    try:
        client = TelegramClient(
            StringSession(),
            app_settings.TELEGRAM_API_ID,
            app_settings.TELEGRAM_API_HASH,
            proxy=build_telethon_proxy(app_settings.TELEGRAM_API_PROXY),
        )
        await client.connect()
        qr_login = await client.qr_login()
    except Exception as exc:
        logger.exception("Userbot qr_login init failed for user {}: {}", user.id, exc)
        await wait_msg.edit_text(
            "❌ Failed to start Telegram login. Please try again later."
        )
        return

    login_task = asyncio.create_task(
        _await_qr_login(
            client=client,
            qr_login=qr_login,
            user_id=user.id,
            chat_id=message.chat.id,
            state=state,
            bot=bot,
        )
    )
    UserBotManager.set_pending(
        user.id,
        {
            "client": client,
            "qr_login": qr_login,
            "login_task": login_task,
        },
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Open login link", url=qr_login.url)],
        ]
    )
    try:
        await wait_msg.delete()
    except Exception:
        pass
    await message.answer_photo(
        photo=_make_qr_input_file(qr_login.url),
        caption=(
            "🔐 <b>Connect your Telegram account</b>\n\n"
            "I'll monitor your channels, groups, and private messages (read-only):\n"
            "• Notify you about interesting channel posts\n"
            "• Notify you about important incoming messages\n"
            "• Add deadlines and meetings to <b>my calendar</b> and remind you\n\n"
            "I will <b>never send messages</b> on your behalf.\n\n"
            "<b>How to authorize:</b>\n"
            "1. Open this chat on Telegram Desktop/Web or another screen.\n"
            "2. On your phone, open <b>Settings → Devices → Link Desktop Device</b>.\n"
            "3. Scan this QR code from that other screen and confirm the new session.\n\n"
            "If your account has Telegram 2-step verification, I'll ask for the password.\n"
            "The QR code expires quickly. If it expires, send <code>/connect_userbot</code> again.\n"
            "Send <code>/cancel_userbot</code> or <code>/cancel</code> to abort."
        ),
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    await message.answer(
        "If you only have one phone available, try the fallback button above or update Telegram first. "
        "Scanning from Telegram Desktop/Web is the most reliable method.",
        parse_mode="HTML",
    )
    await state.set_state(UserBotSetup.waiting_qr)


def _make_qr_input_file(url: str) -> BufferedInputFile:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=12,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return BufferedInputFile(buffer.getvalue(), filename="telegram-login-qr.png")


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
# Step 1 — wait for QR / tg://login confirmation
# ---------------------------------------------------------------------------


@router.message(UserBotSetup.waiting_qr)
async def process_waiting_qr(message: Message, state: FSMContext, session, bot: Bot):
    user = await get_or_create_user(session, message.from_user.id, message.chat.id)
    pending = UserBotManager.get_pending(user.id)
    if not pending:
        await state.clear()
        await message.answer(
            "⚠️ Login link expired. Please start again with /connect_userbot."
        )
        return

    qr_login = pending.get("qr_login")
    expires = getattr(qr_login, "expires", None)
    expires_text = expires.strftime("%H:%M:%S UTC") if expires else "soon"
    await message.answer(
        "Open this chat on Telegram Desktop/Web or another screen, then scan the QR code from your phone through "
        "<b>Settings → Devices → Link Desktop Device</b>.\n\n"
        f"This one-time link expires at approximately <code>{expires_text}</code>.\n"
        "If it has expired, send <code>/connect_userbot</code> again.\n"
        "Send <code>/cancel_userbot</code> or <code>/cancel</code> to abort.",
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Step 3 — 2FA cloud password
# ---------------------------------------------------------------------------


@router.message(UserBotSetup.waiting_password)
async def process_password(message: Message, state: FSMContext, session, bot: Bot):
    password = message.text or ""
    user = await get_or_create_user(session, message.from_user.id, message.chat.id)

    pending = UserBotManager.get_pending(user.id)
    if not pending:
        await message.answer(
            "⚠️ Session expired. Please start over with /connect_userbot."
        )
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

    await _finalize_connection(client, user.id, message.chat.id, state, bot)


# ---------------------------------------------------------------------------
# /disconnect_userbot
# ---------------------------------------------------------------------------


@router.message(Command("disconnect_userbot"))
async def cmd_disconnect_userbot(
    message: Message, state: FSMContext, session, bot: Bot
):
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


async def _await_qr_login(
    *,
    client: TelegramClient,
    qr_login,
    user_id: int,
    chat_id: int,
    state: FSMContext,
    bot: Bot,
) -> None:
    try:
        await qr_login.wait()
    except SessionPasswordNeededError:
        await state.set_state(UserBotSetup.waiting_password)
        await bot.send_message(
            chat_id,
            "🔒 Telegram 2-step verification is enabled.\n"
            "Please send your <b>cloud password</b>.\n"
            "Send <code>/cancel_userbot</code> or <code>/cancel</code> to abort.",
            parse_mode="HTML",
        )
        return
    except asyncio.TimeoutError:
        UserBotManager.clear_pending(user_id)
        try:
            await client.disconnect()
        except Exception:
            pass
        await state.clear()
        await bot.send_message(
            chat_id,
            "⌛ Login link expired. Please send <code>/connect_userbot</code> to generate a new one.",
            parse_mode="HTML",
        )
        return
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception("Userbot qr_login wait failed for user {}: {}", user_id, exc)
        UserBotManager.clear_pending(user_id)
        try:
            await client.disconnect()
        except Exception:
            pass
        await state.clear()
        await bot.send_message(
            chat_id,
            "❌ Telegram login failed. Please try again with <code>/connect_userbot</code>.",
            parse_mode="HTML",
        )
        return

    await _finalize_connection(client, user_id, chat_id, state, bot)


async def _finalize_connection(
    client: TelegramClient,
    user_id: int,
    chat_id: int,
    state: FSMContext,
    bot: Bot,
) -> None:
    """Save the authenticated session to the DB, start monitoring, and confirm."""
    from ...db import get_session
    from ...models.userbot_session import UserBotSession
    from sqlmodel import select

    session_string = client.session.save()
    UserBotManager.clear_pending(user_id)

    async with get_session() as session:
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

    try:
        await client.disconnect()
    except Exception:
        pass

    await UserBotManager.start_client(
        user_id=user_id, session_string=session_string, bot=bot
    )

    await state.clear()
    await bot.send_message(
        chat_id,
        "✅ <b>Telegram account connected!</b>\n\n"
        "I'm now monitoring your account (read-only):\n"
        "• Interesting channel posts → notifications\n"
        "• Important incoming messages → notifications\n"
        "• Deadlines and meetings from messages → <b>my calendar</b> with reminders 📅\n\n"
        "I will <b>never send messages</b> on your behalf.\n\n"
        "Use <code>/userbot_interests topic1, topic2</code> to customise channel filters.\n"
        "Use /calendar to see upcoming events.\n"
        "Use /disconnect_userbot to stop monitoring at any time.",
        parse_mode="HTML",
    )
    logger.info("User {} successfully connected userbot", user_id)
