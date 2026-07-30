import asyncio
from unittest.mock import AsyncMock, MagicMock

from app.services.userbot_manager import UserBotManager


def test_is_client_connected_supports_telethon_sync_probe():
    client = MagicMock()
    client.is_connected.return_value = True

    result = asyncio.run(UserBotManager.is_client_connected(client))

    assert result is True
    client.is_connected.assert_called_once_with()


def test_is_client_connected_remains_compatible_with_async_probe():
    client = MagicMock()
    client.is_connected = AsyncMock(return_value=False)

    result = asyncio.run(UserBotManager.is_client_connected(client))

    assert result is False
    client.is_connected.assert_awaited_once_with()
