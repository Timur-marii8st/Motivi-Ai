from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, TelegramObject
from loguru import logger
from sqlmodel import select

from ...db import AsyncSessionLocal
from ...models.users import User
from ...services.userbot_manager import UserBotManager
from ...services.userbot_monitor import delete_pending_reply


class CommandCancellationMiddleware(BaseMiddleware):
    """
    Global command/state coordinator.

    Behaviour:
    - `/cancel` aborts any active FSM flow.
    - Any other command automatically clears the previous FSM state first,
      then continues into the new command handler.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or not event.text or not event.from_user:
            return await handler(event, data)

        command = _extract_command(event.text)
        if not command:
            return await handler(event, data)

        state: FSMContext | None = data.get("state")
        if state is None:
            if command == "/cancel":
                await event.answer("Нет активного действия для отмены.")
                return None
            return await handler(event, data)

        current_state = await state.get_state()
        if command == "/cancel":
            if not current_state:
                await event.answer("Нет активного действия для отмены.")
                return None
            await _cleanup_active_flow(
                tg_user_id=event.from_user.id,
                current_state=current_state,
                state=state,
            )
            await state.clear()
            await event.answer("❌ Текущее действие отменено.")
            return None

        if current_state:
            await _cleanup_active_flow(
                tg_user_id=event.from_user.id,
                current_state=current_state,
                state=state,
            )
            await state.clear()
            logger.info(
                "Cleared FSM state {} for tg_user_id {} before command {}",
                current_state,
                event.from_user.id,
                command,
            )

        return await handler(event, data)


def _extract_command(text: str) -> str | None:
    token = (text or "").strip().split(maxsplit=1)[0]
    if not token.startswith("/"):
        return None
    return token.split("@", 1)[0].lower()


async def _cleanup_active_flow(
    *,
    tg_user_id: int,
    current_state: str,
    state: FSMContext,
) -> None:
    if current_state.startswith("UserBotSetup:"):
        await _cleanup_userbot_setup(tg_user_id=tg_user_id)
        return

    if current_state.startswith("UserBotReplyEdit:"):
        state_data = await state.get_data()
        pending_key = state_data.get("pending_key")
        if pending_key:
            await delete_pending_reply(pending_key)


async def _cleanup_userbot_setup(*, tg_user_id: int) -> None:
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(User).where(User.tg_user_id == tg_user_id))
            user = result.scalar_one_or_none()
            if not user:
                return

            pending = UserBotManager.get_pending(user.id)
            if not pending:
                return

            try:
                await pending["client"].disconnect()
            except Exception:
                pass

            UserBotManager.clear_pending(user.id)
    except Exception as exc:
        logger.debug("Failed to cleanup userbot setup for tg_user_id {}: {}", tg_user_id, exc)
