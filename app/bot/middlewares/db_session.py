from __future__ import annotations
from typing import Any, Callable, Dict, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ...db import AsyncSessionLocal
from ...models.users import User


class DBSessionMiddleware(BaseMiddleware):
    """Create a DB session for each incoming Telegram event and ensure
    commit/rollback/close semantics even if handlers swallow exceptions.

    We manage the session lifecycle here rather than relying on a shared
    context manager so that handler code that catches exceptions doesn't
    accidentally leave the session in a pending-rollback state.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        session: AsyncSession = AsyncSessionLocal()
        try:
            data["session"] = session
            # Run handler; if it raises we rollback and re-raise
            try:
                result = await handler(event, data)
            except Exception:
                # Ensure DB is rolled back on errors
                try:
                    await session.rollback()
                except Exception:
                    pass
                raise

            # Try to commit any pending work; if commit fails, rollback and raise
            try:
                await _remember_private_topic(session, event)
                await session.commit()
            except Exception:
                try:
                    await session.rollback()
                except Exception:
                    pass
                raise

            return result
        finally:
            try:
                await session.close()
            except Exception:
                pass


async def _remember_private_topic(session: AsyncSession, event: TelegramObject) -> None:
    """Persist the private-chat topic that the user is currently using."""
    message: Message | None = None
    user_id: int | None = None

    if isinstance(event, Message):
        message = event
        user_id = event.from_user.id if event.from_user else None
    elif isinstance(event, CallbackQuery):
        if isinstance(event.message, Message):
            message = event.message
        user_id = event.from_user.id if event.from_user else None

    if not message or not user_id:
        return

    if getattr(message.chat, "type", None) != "private":
        return

    topic_id = getattr(message, "message_thread_id", None)
    try:
        result = await session.execute(select(User).where(User.tg_user_id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            return
        if user.tg_chat_id != message.chat.id:
            user.tg_chat_id = message.chat.id
        if user.tg_private_topic_id != topic_id:
            user.tg_private_topic_id = topic_id
        session.add(user)
    except Exception as exc:
        logger.debug("Could not remember private topic for user {}: {}", user_id, exc)
