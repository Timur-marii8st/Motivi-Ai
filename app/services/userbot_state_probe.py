from __future__ import annotations

import json
import time

from loguru import logger
from telethon import TelegramClient
from telethon.tl.functions.messages import GetPeerDialogsRequest

from ..config import settings as app_settings


def read_marker_ttl_seconds() -> int:
    """Keep read cursors long enough to cover delayed follow-up decisions."""
    followup_window = (
        int(app_settings.USERBOT_DEFAULT_FOLLOWUP_MINUTES) * 60
        + int(app_settings.USERBOT_FOLLOWUP_REMINDER_COOLDOWN_HOURS) * 3600
        + 3600
    )
    return max(30 * 86_400, followup_window)


async def cache_read_marker(user_id: int, chat_id: int, max_read_message_id: int) -> None:
    if max_read_message_id <= 0:
        return
    redis = await _get_redis()
    try:
        await redis.setex(
            read_marker_key(user_id, chat_id),
            read_marker_ttl_seconds(),
            str(max_read_message_id),
        )
    finally:
        await redis.aclose()


async def get_cached_read_marker(user_id: int, chat_id: int) -> int | None:
    redis = await _get_redis()
    try:
        cached_max = await redis.get(read_marker_key(user_id, chat_id))
    finally:
        await redis.aclose()
    return _coerce_int(cached_max)


async def get_read_inbox_max_id(
    client: TelegramClient,
    chat_id: int,
) -> int | None:
    """Fetch the current read cursor for incoming messages in one dialog."""
    try:
        dialogs = await client(GetPeerDialogsRequest(peers=[chat_id]))
    except Exception as exc:
        logger.debug("Could not fetch read cursor for chat {}: {}", chat_id, exc)
        return None

    for dialog in getattr(dialogs, "dialogs", []) or []:
        read_max = _coerce_int(getattr(dialog, "read_inbox_max_id", None))
        if read_max is not None:
            return read_max
    return None


async def cache_manual_outgoing(
    *,
    user_id: int,
    chat_id: int,
    message_id: int | None,
) -> None:
    redis = await _get_redis()
    try:
        await redis.setex(
            manual_outgoing_key(user_id, chat_id),
            86_400,
            json.dumps(
                {
                    "message_id": message_id,
                    "ts": int(time.time()),
                },
                ensure_ascii=False,
            ),
        )
    finally:
        await redis.aclose()


async def has_cached_manual_outgoing_after(
    *,
    user_id: int,
    chat_id: int,
    message_id: int,
    message_ts: int = 0,
) -> bool:
    redis = await _get_redis()
    try:
        raw = await redis.get(manual_outgoing_key(user_id, chat_id))
    finally:
        await redis.aclose()
    if not raw:
        return False
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return False
    outgoing_id = _coerce_int(data.get("message_id"))
    if outgoing_id is not None and outgoing_id > message_id:
        return True
    outgoing_ts = _coerce_int(data.get("ts"))
    return bool(outgoing_ts and message_ts and outgoing_ts > message_ts)


async def has_live_outgoing_after(
    client: TelegramClient,
    chat_id: int,
    message_id: int,
    *,
    limit: int = 200,
) -> bool:
    """Scan recent newer messages for one sent by the connected user account."""
    try:
        async for message in client.iter_messages(
            chat_id,
            min_id=message_id,
            limit=limit,
        ):
            current_id = _coerce_int(getattr(message, "id", None))
            if current_id is None or current_id <= message_id:
                continue
            if getattr(message, "out", False):
                return True
    except Exception as exc:
        logger.debug(
            "Could not scan outgoing messages for chat {} after {}: {}",
            chat_id,
            message_id,
            exc,
        )
    return False


def read_marker_key(user_id: int, chat_id: int) -> str:
    return f"ub_read:{user_id}:{chat_id}"


def manual_outgoing_key(user_id: int, chat_id: int) -> str:
    return f"ub_outgoing:{user_id}:{chat_id}"


async def _get_redis():
    from redis.asyncio import Redis

    return Redis.from_url(app_settings.REDIS_URL)


def _coerce_int(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode(errors="ignore")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
