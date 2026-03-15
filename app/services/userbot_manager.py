"""
UserBotManager — lifecycle management for Telethon (MTProto) clients.

One TelegramClient is created per bot-user who has connected their personal
Telegram account. Clients are stored in an in-process registry and restarted
on application startup from the encrypted sessions in the database.

Design decisions
----------------
* Human-in-the-loop: event handlers monitor messages read-only.
  Write operations (send_message, send_chat_action) are ONLY performed
  after explicit user approval via bot callback buttons.
* Pending auth dict: during the FSM authentication flow the partially-created
  TelegramClient lives in ``_pending`` (keyed by bot user_id). This avoids
  persisting an unverified session to the DB.
"""
from __future__ import annotations

from typing import Optional

from loguru import logger
from telethon import TelegramClient
from telethon.sessions import StringSession

from ..config import settings as app_settings

# ── Active clients: bot user_id → TelegramClient ──────────────────────────────
_clients: dict[int, TelegramClient] = {}

# ── Pending auth clients (not yet fully signed-in) ────────────────────────────
# Structure: {user_id: {"client": TelegramClient, "phone": str, "phone_code_hash": str}}
_pending: dict[int, dict] = {}


class UserBotManager:
    # ------------------------------------------------------------------ #
    # Startup / shutdown                                                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    async def start_all(bot) -> None:
        """
        Called once during application startup.
        Loads every active UserBotSession from the DB and starts a client.
        """
        if not app_settings.TELEGRAM_API_ID or not app_settings.TELEGRAM_API_HASH:
            logger.warning(
                "TELEGRAM_API_ID / TELEGRAM_API_HASH not configured — userbot disabled"
            )
            return

        from ..db import get_session
        from ..models.userbot_session import UserBotSession
        from sqlmodel import select

        try:
            async with get_session() as session:
                result = await session.execute(
                    select(UserBotSession).where(UserBotSession.is_active == True)  # noqa: E712
                )
                rows = result.scalars().all()

            for row in rows:
                try:
                    await UserBotManager.start_client(
                        user_id=row.user_id,
                        session_string=row.session_string or "",
                        bot=bot,
                    )
                except Exception as exc:
                    logger.error(
                        "Failed to start userbot for user {}: {}", row.user_id, exc
                    )

            logger.info("UserBotManager: {} client(s) started", len(_clients))
        except Exception as exc:
            logger.error("UserBotManager.start_all failed: {}", exc)

    @staticmethod
    async def stop_all() -> None:
        """Disconnect every active Telethon client gracefully."""
        for uid in list(_clients.keys()):
            await UserBotManager.stop_client(uid)
        logger.info("UserBotManager: all clients stopped")

    # ------------------------------------------------------------------ #
    # Individual client management                                         #
    # ------------------------------------------------------------------ #

    @staticmethod
    async def start_client(user_id: int, session_string: str, bot) -> None:
        """
        Connect a Telethon client from an existing StringSession and register
        event handlers.  If the session is expired/invalid the DB record is
        deactivated and nothing is added to ``_clients``.
        """
        from .userbot_monitor import setup_handlers
        if user_id not in _clients and len(_clients) >= app_settings.USERBOT_MAX_ACTIVE_CLIENTS:
            logger.warning(
                "Userbot active client cap reached (%s). Skipping user %s",
                app_settings.USERBOT_MAX_ACTIVE_CLIENTS,
                user_id,
            )
            return

        client = TelegramClient(
            StringSession(session_string),
            app_settings.TELEGRAM_API_ID,
            app_settings.TELEGRAM_API_HASH,
        )
        await client.connect()

        if not await client.is_user_authorized():
            logger.warning(
                "Userbot session for user {} is invalid/expired — deactivating", user_id
            )
            await UserBotManager._deactivate_session(user_id)
            try:
                await client.disconnect()
            except Exception:
                pass
            return

        setup_handlers(client, user_id, bot)
        _clients[user_id] = client
        logger.info("Userbot client started for user {}", user_id)

    @staticmethod
    async def stop_client(user_id: int) -> None:
        """Disconnect and remove a user's client from the registry."""
        client = _clients.pop(user_id, None)
        if client:
            try:
                await client.disconnect()
            except Exception as exc:
                logger.warning(
                    "Error disconnecting userbot for user {}: {}", user_id, exc
                )
            logger.info("Userbot client stopped for user {}", user_id)

    @staticmethod
    def get_client(user_id: int) -> Optional[TelegramClient]:
        return _clients.get(user_id)

    # ------------------------------------------------------------------ #
    # Pending auth management (used by the FSM router)                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def get_pending(user_id: int) -> Optional[dict]:
        return _pending.get(user_id)

    @staticmethod
    def set_pending(user_id: int, data: dict) -> None:
        _pending[user_id] = data

    @staticmethod
    def clear_pending(user_id: int) -> None:
        _pending.pop(user_id, None)

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    async def _deactivate_session(user_id: int) -> None:
        from ..db import get_session
        from ..models.userbot_session import UserBotSession
        from sqlmodel import select

        try:
            async with get_session() as session:
                result = await session.execute(
                    select(UserBotSession).where(UserBotSession.user_id == user_id)
                )
                row = result.scalar_one_or_none()
                if row:
                    row.is_active = False
                    row.touch()
                    session.add(row)
                    await session.commit()
        except Exception as exc:
            logger.error(
                "Failed to deactivate userbot session for user {}: {}", user_id, exc
            )
