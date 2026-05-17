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
from io import BytesIO
import random

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
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
from telethon.tl.functions.messages import SetTypingRequest
from telethon.tl.types import SendMessageTypingAction

from ...config import settings as app_settings
from ...services.userbot_manager import UserBotManager
from ...services.userbot_monitor import (
    build_userbot_approval_keyboard,
    check_reply_rate_limit,
    delete_pending_action_plan,
    delete_pending_reply,
    get_pending_action_plan,
    get_pending_reply,
    increment_reply_counter,
    mark_bot_sent_reply,
    save_pending_action_plan,
)
from ...services.profile_services import get_or_create_user
from ...utils.telegram_mtproto import build_telethon_proxy
from ..states import UserBotSetup, UserBotReplyEdit, UserBotActionStepEdit

router = Router(name="userbot")


# ===========================================================================
# Reply approval callbacks
# ===========================================================================

@router.callback_query(F.data.startswith("ub_send:"))
async def cb_approve_reply(callback: CallbackQuery, session, bot: Bot):
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

    if await _is_reply_target_assistant_bot(pending["chat_id"], bot):
        await delete_pending_reply(pending_key)
        await callback.answer("Internal bot chat is ignored.", show_alert=True)
        await callback.message.edit_text(
            callback.message.text + "\n\n🚫 <i>Internal bot chat ignored</i>",
            parse_mode="HTML",
            reply_markup=None,
        )
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
        await _mark_thread_replied_from_pending(
            user_id=user.id,
            pending=pending,
            reply_text=reply_text,
        )
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
    await _mark_thread_dismissed_from_pending(user_id=user.id, pending=pending)
    await callback.answer("🚫 Dismissed")
    await callback.message.edit_text(
        callback.message.text + "\n\n🚫 <i>Dismissed</i>",
        parse_mode="HTML",
        reply_markup=None,
    )


# ===========================================================================
# Action-plan approval callbacks
# ===========================================================================

@router.callback_query(F.data.startswith("ub_plan_step:"))
async def cb_run_action_plan_step(callback: CallbackQuery, session, bot: Bot):
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("❌ Invalid action")
        return

    pending_key = parts[1]
    try:
        step_index = int(parts[2])
    except ValueError:
        await callback.answer("❌ Invalid action")
        return

    user = await get_or_create_user(session, callback.from_user.id, callback.message.chat.id)
    action_plan = await _get_owned_action_plan(pending_key, user.id, callback)
    if not action_plan:
        return

    ok, message = await _run_action_plan_step(
        user_id=user.id,
        action_plan=action_plan,
        step_index=step_index,
        session=session,
        bot=bot,
    )
    if ok:
        await save_pending_action_plan(pending_key, action_plan)
        await callback.answer(message)
        await _refresh_action_plan_message(callback, pending_key, action_plan)
    else:
        await callback.answer(message, show_alert=True)


@router.callback_query(F.data.startswith("ub_plan_all:"))
async def cb_run_safe_action_plan_steps(callback: CallbackQuery, session, bot: Bot):
    parts = callback.data.split(":")
    if len(parts) != 2:
        await callback.answer("❌ Invalid action")
        return

    pending_key = parts[1]
    user = await get_or_create_user(session, callback.from_user.id, callback.message.chat.id)
    action_plan = await _get_owned_action_plan(pending_key, user.id, callback)
    if not action_plan:
        return

    ran = 0
    contact_steps_left = False
    for index, step in enumerate(action_plan.get("steps", [])):
        if step.get("status") == "done":
            continue
        if step.get("requires_separate_approval"):
            contact_steps_left = True
            continue
        ok, _ = await _run_action_plan_step(
            user_id=user.id,
            action_plan=action_plan,
            step_index=index,
            session=session,
            bot=bot,
        )
        if ok:
            ran += 1

    if ran:
        await save_pending_action_plan(pending_key, action_plan)
        await _refresh_action_plan_message(callback, pending_key, action_plan)

    if contact_steps_left:
        await callback.answer(
            f"✅ Ran {ran} safe step(s). Contact messages need individual approval.",
            show_alert=True,
        )
    elif ran:
        await callback.answer(f"✅ Ran {ran} step(s).")
    else:
        await callback.answer("Nothing safe to run.", show_alert=True)


@router.callback_query(F.data.startswith("ub_plan_edit:"))
async def cb_edit_action_plan_step(callback: CallbackQuery, state: FSMContext, session):
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("❌ Invalid action")
        return

    pending_key = parts[1]
    try:
        step_index = int(parts[2])
    except ValueError:
        await callback.answer("❌ Invalid action")
        return

    user = await get_or_create_user(session, callback.from_user.id, callback.message.chat.id)
    action_plan = await _get_owned_action_plan(pending_key, user.id, callback)
    if not action_plan:
        return

    step = _get_action_plan_step(action_plan, step_index)
    if not step or step.get("type") not in {"reply_to_sender", "send_message_to_contact"}:
        await callback.answer("This step cannot be edited.", show_alert=True)
        return

    await state.set_state(UserBotActionStepEdit.waiting_text)
    await state.update_data(pending_key=pending_key, step_index=step_index)
    await callback.answer()
    await callback.message.answer(
        f"✏️ Type edited text for action step #{step_index + 1}.\n"
        "It will be sent after this message. Send /cancel_action to abort.",
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("ub_plan_dismiss:"))
async def cb_dismiss_action_plan(callback: CallbackQuery, session):
    parts = callback.data.split(":")
    if len(parts) != 2:
        await callback.answer("❌ Invalid action")
        return

    pending_key = parts[1]
    user = await get_or_create_user(session, callback.from_user.id, callback.message.chat.id)
    action_plan = await get_pending_action_plan(pending_key)
    if not action_plan:
        await callback.answer("⏰ This action plan has expired.", show_alert=True)
        await _mark_message_expired(callback)
        return
    if action_plan and action_plan.get("user_id") not in {None, user.id}:
        await callback.answer("❌ Not your action plan.", show_alert=True)
        return

    await delete_pending_action_plan(pending_key)
    await callback.answer("🚫 Plan dismissed")
    suggestions_count = len(action_plan.get("suggestions") or []) if action_plan else 0
    await callback.message.edit_text(
        callback.message.text + "\n\n🚫 <i>Action plan dismissed</i>",
        parse_mode="HTML",
        reply_markup=build_userbot_approval_keyboard(pending_key, suggestions_count),
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
        pending = await get_pending_reply(pending_key)
        await delete_pending_reply(pending_key)
        if pending:
            await _mark_thread_dismissed_from_pending(
                user_id=pending["user_id"],
                pending=pending,
            )
    await state.clear()
    await message.answer("❌ Reply cancelled.")


@router.message(Command("cancel_action"))
async def cmd_cancel_action(message: Message, state: FSMContext):
    """Cancel editing an action-plan step."""
    await state.clear()
    await message.answer("❌ Action step cancelled.")


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

    if await _is_reply_target_assistant_bot(pending["chat_id"], bot):
        await delete_pending_reply(pending_key)
        await state.clear()
        await message.answer("🚫 Internal bot chat ignored.")
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
        await _mark_thread_replied_from_pending(
            user_id=user.id,
            pending=pending,
            reply_text=custom_text,
        )
        await message.answer(
            f"✅ <b>Reply sent to {_esc(pending['sender_name'])}:</b>\n"
            f"<i>{_esc(custom_text[:200])}</i>",
            parse_mode="HTML",
        )
    else:
        await message.answer("❌ Failed to send. Your Telethon session may have expired.")


@router.message(UserBotActionStepEdit.waiting_text)
async def process_action_step_edit(message: Message, state: FSMContext, session, bot: Bot):
    """Send an edited action-plan message step."""
    custom_text = (message.text or "").strip()
    if not custom_text:
        await message.answer("Please type the edited text or send /cancel_action to abort.")
        return

    data = await state.get_data()
    pending_key = data.get("pending_key")
    step_index = data.get("step_index")
    if pending_key is None or step_index is None:
        await state.clear()
        await message.answer("⚠️ Session lost. Please try again from the notification.")
        return

    user = await get_or_create_user(session, message.from_user.id, message.chat.id)
    action_plan = await get_pending_action_plan(pending_key)
    if not action_plan:
        await state.clear()
        await message.answer("⏰ This action plan has expired.")
        return
    if action_plan.get("user_id") != user.id:
        await state.clear()
        await message.answer("❌ Not your action plan.")
        return

    step = _get_action_plan_step(action_plan, int(step_index))
    if not step or step.get("type") not in {"reply_to_sender", "send_message_to_contact"}:
        await state.clear()
        await message.answer("This step cannot be edited.")
        return

    step["text"] = custom_text[:900]
    ok, result_message = await _run_action_plan_step(
        user_id=user.id,
        action_plan=action_plan,
        step_index=int(step_index),
        session=session,
        bot=bot,
    )
    await state.clear()

    if ok:
        await save_pending_action_plan(pending_key, action_plan)
        await message.answer(f"✅ {result_message}")
    else:
        await message.answer(f"❌ {result_message}")


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
    return await _send_message_with_human_simulation(
        user_id=user_id,
        chat_id=chat_id,
        text=text,
        reply_to_msg_id=reply_to_msg_id,
    )


async def _send_message_with_human_simulation(
    *,
    user_id: int,
    chat_id: int,
    text: str,
    reply_to_msg_id: int | None = None,
) -> bool:
    client = UserBotManager.get_client(user_id)
    if not client:
        logger.warning("No active Telethon client for user {} — cannot send message", user_id)
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

        # 4. Send the message
        send_kwargs = {"entity": chat_id, "message": text}
        if reply_to_msg_id is not None:
            send_kwargs["reply_to"] = reply_to_msg_id
        await client.send_message(**send_kwargs)

        logger.info(
            "Userbot: sent approved message for user {} to chat {} (delay={:.1f}s)",
            user_id, chat_id, total_delay,
        )
        return True

    except Exception as exc:
        logger.error(
            "Userbot: failed to send message for user {} to chat {}: {}",
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

        restart_msg = await message.answer("🔴 Session saved but client not running. Restarting…")
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
        await wait_msg.edit_text("❌ Failed to start Telegram login. Please try again later.")
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
            "I'll monitor your channels, groups, and private messages:\n"
            "• Notify you about interesting channel posts\n"
            "• Suggest replies for incoming messages\n"
            "• Send replies <b>only after your approval</b>\n\n"
            "<b>How to authorize:</b>\n"
            "1. Open this chat on Telegram Desktop/Web or another screen.\n"
            "2. On your phone, open <b>Settings → Devices → Link Desktop Device</b>.\n"
            "3. Scan this QR code from that other screen and confirm the new session.\n\n"
            "If your account has Telegram 2-step verification enabled, I'll ask for the cloud password next.\n\n"
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
        await message.answer("⚠️ Login link expired. Please start again with /connect_userbot.")
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

    await _finalize_connection(client, user.id, message.chat.id, state, bot)


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


# ---------------------------------------------------------------------------
# /userbot_pending — durable open reply queue
# ---------------------------------------------------------------------------

@router.message(Command("userbot_pending"))
async def cmd_userbot_pending(message: Message, session):
    user = await get_or_create_user(session, message.from_user.id, message.chat.id)

    threads = await _load_open_important_threads(session=session, user_id=user.id)
    if not threads:
        await message.answer("No important userbot replies are pending.")
        return

    lines = ["<b>Pending userbot replies</b>"]
    buttons: list[list[InlineKeyboardButton]] = []

    for idx, thread in enumerate(threads, 1):
        thread_id = getattr(thread, "id", None)
        sender = getattr(thread, "sender_name", None) or "Unknown sender"
        chat_type = getattr(thread, "chat_type", None) or "chat"
        summary = (
            getattr(thread, "message_summary", None)
            or getattr(thread, "summary", None)
            or "No summary available"
        )
        summary = _compact(summary, 180)
        lines.append(
            f"\n<b>{idx}. {_esc(sender)}</b> <i>({_esc(chat_type)})</i>\n"
            f"{_esc(summary)}"
        )
        if thread_id is not None:
            buttons.append([
                InlineKeyboardButton(
                    text=f"Dismiss #{idx}",
                    callback_data=f"ub_thread_dismiss:{thread_id}",
                )
            ])

    await message.answer(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None,
    )


@router.callback_query(F.data.startswith("ub_thread_dismiss:"))
async def cb_dismiss_persistent_thread(callback: CallbackQuery, session):
    parts = callback.data.split(":")
    if len(parts) != 2:
        await callback.answer("Invalid action")
        return

    try:
        thread_id = int(parts[1])
    except ValueError:
        await callback.answer("Invalid action")
        return

    user = await get_or_create_user(session, callback.from_user.id, callback.message.chat.id)
    await _mark_thread_dismissed(user_id=user.id, thread_id=thread_id)
    await callback.answer("Dismissed")
    await callback.message.edit_reply_markup(reply_markup=None)


# ===========================================================================
# Internal helpers
# ===========================================================================

async def _get_owned_action_plan(
    pending_key: str,
    user_id: int,
    callback: CallbackQuery,
) -> dict | None:
    action_plan = await get_pending_action_plan(pending_key)
    if not action_plan:
        await callback.answer("⏰ This action plan has expired.", show_alert=True)
        await _mark_message_expired(callback)
        return None
    if action_plan.get("user_id") != user_id:
        await callback.answer("❌ Not your action plan.", show_alert=True)
        return None
    return action_plan


def _get_action_plan_step(action_plan: dict, step_index: int) -> dict | None:
    steps = action_plan.get("steps")
    if not isinstance(steps, list) or step_index < 0 or step_index >= len(steps):
        return None
    step = steps[step_index]
    return step if isinstance(step, dict) else None


async def _run_action_plan_step(
    *,
    user_id: int,
    action_plan: dict,
    step_index: int,
    session,
    bot: Bot,
) -> tuple[bool, str]:
    step = _get_action_plan_step(action_plan, step_index)
    if not step:
        return False, "Invalid action step."
    if step.get("status") == "done":
        return False, "This step was already completed."

    step_type = step.get("type")
    if step_type == "reply_to_sender":
        return await _run_reply_to_sender_step(
            user_id=user_id,
            action_plan=action_plan,
            step=step,
            bot=bot,
        )
    if step_type == "send_message_to_contact":
        return await _run_send_message_to_contact_step(
            user_id=user_id,
            step=step,
            bot=bot,
        )
    if step_type == "create_reminder":
        return await _run_create_reminder_step(
            user_id=user_id,
            action_plan=action_plan,
            step=step,
            session=session,
            bot=bot,
        )
    return False, "This action step is not executable."


async def _run_reply_to_sender_step(
    *,
    user_id: int,
    action_plan: dict,
    step: dict,
    bot: Bot,
) -> tuple[bool, str]:
    chat_id = action_plan.get("source_chat_id")
    message_id = action_plan.get("source_message_id")
    text = (step.get("text") or "").strip()
    if not chat_id or not message_id or not text:
        return False, "Reply step is missing required data."
    if await _is_reply_target_assistant_bot(chat_id, bot):
        return False, "Internal bot chat is ignored."
    if not await check_reply_rate_limit(user_id):
        return False, f"Daily reply limit reached ({app_settings.USERBOT_MAX_REPLIES_PER_DAY}/day)."

    success = await _send_message_with_human_simulation(
        user_id=user_id,
        chat_id=chat_id,
        text=text,
        reply_to_msg_id=message_id,
    )
    if not success:
        return False, "Failed to send reply. Session may be expired."

    await increment_reply_counter(user_id)
    await _mark_thread_replied_from_pending(
        user_id=user_id,
        pending=action_plan,
        reply_text=text,
    )
    step["status"] = "done"
    return True, "Step sent."


async def _run_send_message_to_contact_step(
    *,
    user_id: int,
    step: dict,
    bot: Bot,
) -> tuple[bool, str]:
    chat_id = step.get("target_chat_id")
    text = (step.get("text") or "").strip()
    if not chat_id or not text:
        return False, "Contact message step is missing required data."
    if await _is_reply_target_assistant_bot(chat_id, bot):
        return False, "Internal bot chat is ignored."
    if not await check_reply_rate_limit(user_id):
        return False, f"Daily reply limit reached ({app_settings.USERBOT_MAX_REPLIES_PER_DAY}/day)."

    success = await _send_message_with_human_simulation(
        user_id=user_id,
        chat_id=chat_id,
        text=text,
    )
    if not success:
        return False, "Failed to send message. Session may be expired."

    await increment_reply_counter(user_id)
    step["status"] = "done"
    return True, f"Step sent to {step.get('target_label', 'contact')}."


async def _run_create_reminder_step(
    *,
    user_id: int,
    action_plan: dict,
    step: dict,
    session,
    bot: Bot,
) -> tuple[bool, str]:
    message_text = (step.get("message_text") or "").strip()
    reminder_datetime_iso = (step.get("reminder_datetime_iso") or "").strip()
    owner_tg_chat_id = action_plan.get("owner_tg_chat_id")
    if not message_text or not reminder_datetime_iso or not owner_tg_chat_id:
        return False, "Reminder step is missing required data."

    try:
        from ...services.tool_executor import ToolExecutor

        executor = ToolExecutor(session=session, bot=bot)
        result = await executor._schedule_reminder(
            {
                "message_text": message_text,
                "reminder_datetime_iso": reminder_datetime_iso,
            },
            chat_id=owner_tg_chat_id,
            user_id=user_id,
        )
    except Exception as exc:
        logger.debug("Userbot action reminder step failed: {}", exc)
        return False, "Failed to create reminder."

    if not result.get("success"):
        return False, str(result.get("error") or "Failed to create reminder.")

    step["status"] = "done"
    step["job_id"] = result.get("job_id")
    return True, "Reminder created."


async def _refresh_action_plan_message(
    callback: CallbackQuery,
    pending_key: str,
    action_plan: dict,
) -> None:
    try:
        notification = action_plan.get("notification_text") or callback.message.text
        status = _format_action_plan_status(action_plan)
        reply_pending_key = action_plan.get("reply_pending_key") or pending_key
        suggestions = action_plan.get("suggestions") or []
        await callback.message.edit_text(
            notification + status,
            parse_mode="HTML",
            reply_markup=build_userbot_approval_keyboard(
                reply_pending_key,
                len(suggestions),
                action_plan=action_plan,
            ),
        )
    except Exception as exc:
        logger.debug("Userbot: failed to refresh action plan message: {}", exc)


def _format_action_plan_status(action_plan: dict) -> str:
    lines = ["", "<b>Action status:</b>"]
    for index, step in enumerate(action_plan.get("steps", []), 1):
        status = "done" if step.get("status") == "done" else "pending"
        lines.append(f"{index}. {_esc(status)}")
    return "\n" + "\n".join(lines)


async def _mark_thread_replied_from_pending(
    *,
    user_id: int,
    pending: dict,
    reply_text: str,
) -> None:
    thread_id = pending.get("thread_id")
    if not thread_id:
        return

    try:
        from ...db import get_session
        from ...services.userbot_thread_service import UserBotThreadService

        async with get_session() as db_session:
            service = UserBotThreadService()
            await service.mark_replied(
                session=db_session,
                user_id=user_id,
                thread_id=thread_id,
            )
    except Exception as exc:
        logger.debug("Userbot: failed to mark thread {} replied: {}", thread_id, exc)


async def _mark_thread_dismissed_from_pending(*, user_id: int, pending: dict | None) -> None:
    if not pending:
        return
    thread_id = pending.get("thread_id")
    if thread_id:
        await _mark_thread_dismissed(user_id=user_id, thread_id=thread_id)


async def _mark_thread_dismissed(*, user_id: int, thread_id: int) -> None:
    try:
        from ...db import get_session
        from ...models.userbot_thread import UserBotThread
        from ...services.userbot_thread_service import UserBotThreadService

        async with get_session() as db_session:
            thread = await db_session.get(UserBotThread, thread_id)
            if not thread or getattr(thread, "user_id", None) != user_id:
                return
            service = UserBotThreadService()
            await service.mark_dismissed(
                db_session,
                thread_id=thread_id,
            )
    except Exception as exc:
        logger.debug("Userbot: failed to dismiss thread {}: {}", thread_id, exc)


async def _load_open_important_threads(*, session, user_id: int) -> list:
    try:
        from sqlmodel import select
        from ...models.userbot_thread import UserBotThread

        stmt = select(UserBotThread).where(UserBotThread.user_id == user_id)
        if hasattr(UserBotThread, "status"):
            stmt = stmt.where(UserBotThread.status.in_(["open", "reminded", "pending"]))
        if hasattr(UserBotThread, "requires_response"):
            stmt = stmt.where(UserBotThread.requires_response == True)  # noqa: E712
        elif hasattr(UserBotThread, "needs_reply"):
            stmt = stmt.where(UserBotThread.needs_reply == True)  # noqa: E712
        if hasattr(UserBotThread, "importance"):
            stmt = stmt.where(UserBotThread.importance >= 3)
        order_by = []
        if hasattr(UserBotThread, "importance"):
            order_by.append(UserBotThread.importance.desc())
        if hasattr(UserBotThread, "updated_at"):
            order_by.append(UserBotThread.updated_at.desc())
        elif hasattr(UserBotThread, "created_at"):
            order_by.append(UserBotThread.created_at.desc())
        if order_by:
            stmt = stmt.order_by(*order_by)
        stmt = stmt.limit(10)

        result = await session.execute(stmt)
        return list(result.scalars().all())
    except Exception as exc:
        logger.debug("Userbot: could not load pending threads for user {}: {}", user_id, exc)
        return []


def _compact(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


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

    await UserBotManager.start_client(user_id=user_id, session_string=session_string, bot=bot)

    await state.clear()
    await bot.send_message(
        chat_id,
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


async def _is_reply_target_assistant_bot(chat_id: int, bot: Bot) -> bool:
    try:
        bot_user_id = int((await bot.get_me()).id)
        return int(chat_id) == bot_user_id
    except Exception as exc:
        logger.debug("Could not check assistant bot reply target: {}", exc)
        return False


def _esc(text: str) -> str:
    """Escape HTML special characters for Telegram HTML parse mode."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
