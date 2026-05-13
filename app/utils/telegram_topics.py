from __future__ import annotations

from typing import Any


def topic_kwargs_for_user(user: Any) -> dict[str, int]:
    """Return Bot API kwargs for the user's active private-chat topic."""
    topic_id = getattr(user, "tg_private_topic_id", None)
    if isinstance(topic_id, int) and topic_id > 0:
        return {"message_thread_id": topic_id}
    return {}
