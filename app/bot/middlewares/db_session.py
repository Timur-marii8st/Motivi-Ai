from __future__ import annotations
from typing import Any, Callable, Dict, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import AsyncSessionLocal


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