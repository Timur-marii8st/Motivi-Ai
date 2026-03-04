from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any, Callable

from loguru import logger
from sqlalchemy import event
from sqlalchemy.orm import Session

from ..config import settings
from ..models.core_memory import CoreMemory
from ..models.episode import Episode
from ..models.habit import Habit
from ..models.plan import Plan
from ..models.settings import UserSettings
from ..models.userbot_session import UserBotSession
from ..models.users import User
from ..models.working_memory import WorkingMemory, WorkingMemoryEntry

OwnerGetter = Callable[[Any], int | None]


def _derive_integrity_key() -> bytes:
    raw_key = (settings.ENCRYPTION_KEY or "").strip().encode("utf-8")
    try:
        decoded = base64.urlsafe_b64decode(raw_key)
        if decoded:
            raw_key = decoded
    except Exception:
        pass
    return hashlib.sha256(raw_key + b":row-integrity:v1").digest()


_INTEGRITY_KEY = _derive_integrity_key()


def _normalize(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in sorted(value.items(), key=lambda x: str(x[0]))}
    if isinstance(value, (list, tuple)):
        return [_normalize(v) for v in value]
    return str(value)


def _compute_signature(table_name: str, owner_id: int, fields: dict[str, Any]) -> str:
    payload = {
        "table": table_name,
        "owner_id": owner_id,
        "fields": _normalize(fields),
    }
    message = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hmac.new(_INTEGRITY_KEY, message, hashlib.sha256).hexdigest()


_TRACKED_MODELS: dict[type, tuple[OwnerGetter, tuple[str, ...]]] = {
    User: (lambda obj: obj.tg_user_id, ("name", "occupation_json")),
    CoreMemory: (lambda obj: obj.user_id, ("core_text", "sleep_schedule_json")),
    WorkingMemory: (lambda obj: obj.user_id, ("working_memory_text",)),
    WorkingMemoryEntry: (lambda obj: obj.user_id, ("working_memory_text",)),
    Episode: (lambda obj: obj.user_id, ("text", "metadata_json")),
    UserSettings: (lambda obj: obj.user_id, ("summary_preferences_json", "userbot_channel_interests")),
    Habit: (lambda obj: obj.user_id, ("description",)),
    Plan: (lambda obj: obj.user_id, ("content",)),
    UserBotSession: (lambda obj: obj.user_id, ("session_string", "phone_number")),
}


def _sign_instance(instance: Any) -> None:
    tracked = _TRACKED_MODELS.get(type(instance))
    if tracked is None:
        return
    owner_getter, field_names = tracked
    owner_id = owner_getter(instance)
    if owner_id is None:
        return
    fields = {field_name: getattr(instance, field_name, None) for field_name in field_names}
    instance.integrity_sig = _compute_signature(instance.__tablename__, int(owner_id), fields)


def recalculate_integrity_signature(instance: Any) -> None:
    _sign_instance(instance)


def _verify_instance(instance: Any) -> None:
    tracked = _TRACKED_MODELS.get(type(instance))
    if tracked is None:
        return
    current_sig = getattr(instance, "integrity_sig", None)
    if not current_sig:
        if settings.INTEGRITY_STRICT_MODE:
            logger.error(
                "Missing integrity signature for %s id=%s in strict mode",
                instance.__tablename__,
                getattr(instance, "id", None),
            )
            raise RuntimeError(
                f"Missing integrity signature for {instance.__tablename__} id={getattr(instance, 'id', None)}"
            )
        return
    owner_getter, field_names = tracked
    owner_id = owner_getter(instance)
    if owner_id is None:
        return
    fields = {field_name: getattr(instance, field_name, None) for field_name in field_names}
    expected = _compute_signature(instance.__tablename__, int(owner_id), fields)
    current = str(current_sig)
    if not hmac.compare_digest(expected, current):
        logger.error(
            "Integrity signature mismatch for %s id=%s owner=%s",
            instance.__tablename__,
            getattr(instance, "id", None),
            owner_id,
        )
        raise RuntimeError(
            f"Integrity check failed for {instance.__tablename__} id={getattr(instance, 'id', None)}"
        )


@event.listens_for(Session, "before_flush")
def _before_flush(session: Session, flush_context, instances) -> None:
    for instance in session.new:
        _sign_instance(instance)
    for instance in session.dirty:
        _sign_instance(instance)


_registered = False


def register_row_integrity_hooks() -> None:
    global _registered
    if _registered:
        return

    def _on_load(target, context):
        _verify_instance(target)

    for model_cls in _TRACKED_MODELS:
        event.listen(model_cls, "load", _on_load, propagate=True)
    _registered = True
