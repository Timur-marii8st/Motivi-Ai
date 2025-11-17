from __future__ import annotations
from typing import Optional, List, Dict, Any
import httpx

class MCPClient:
    """
    HTTP client to call MCP tool server.
    """
    def __init__(self, base_url: str, secret_token: str):
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {secret_token}"}
        self._client = httpx.AsyncClient(timeout=30.0)

    async def send_file(self, chat_id: int, file_path: str, caption: Optional[str] = None) -> int:
        """Returns message_id."""
        payload = {"chat_id": chat_id, "file_path": file_path, "caption": caption}
        resp = await self._client.post(f"{self.base_url}/tools/send_file", json=payload, headers=self.headers)
        resp.raise_for_status()
        return resp.json()["message_id"]

    async def send_telegram_message_and_pin(self, chat_id: int, message_text: str, disable_notification: bool = True):
        payload = {"chat_id": chat_id, "message_text": message_text, "disable_notification": disable_notification}
        resp = await self._client.post(f"{self.base_url}/tools/send_telegram_message_and_pin", json=payload, headers=self.headers)
        resp.raise_for_status()