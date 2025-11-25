from __future__ import annotations

import base64
import json
from typing import Any, Callable, Optional

from loguru import logger
from sqlalchemy.types import TypeDecorator, Text

from .encryption_manager import get_data_encryptor


_VERSION_PREFIX = "v1:"


def _encode_ciphertext(ciphertext: bytes) -> str:
    return _VERSION_PREFIX + base64.urlsafe_b64encode(ciphertext).decode("ascii")


def _decode_ciphertext(payload: str) -> bytes:
    if not payload.startswith(_VERSION_PREFIX):
        raise ValueError("Ciphertext missing version prefix")
    b64_part = payload[len(_VERSION_PREFIX) :]
    return base64.urlsafe_b64decode(b64_part.encode("ascii"))


def _prepare_aad(label: str | None) -> bytes:
    if not label:
        return b""
    return label.encode("utf-8")


class _EncryptedBase(TypeDecorator):
    """
    Base class for transparent column encryption.
    """

    impl = Text
    cache_ok = True

    def __init__(
        self,
        *,
        column_label: str,
        serializer: Callable[[Any], bytes],
        deserializer: Callable[[bytes], Any],
    ) -> None:
        super().__init__()
        self._aad = _prepare_aad(column_label)
        self._label = column_label
        self._serializer = serializer
        self._deserializer = deserializer
        self._legacy_warned = False

    def process_bind_param(self, value: Any, dialect) -> Optional[str]:
        if value is None:
            return None
        encryptor = get_data_encryptor()
        serialized = self._serializer(value)
        ciphertext = encryptor.encrypt(serialized, aad=self._aad)
        return _encode_ciphertext(ciphertext)

    def process_result_value(self, value: Any, dialect) -> Any:
        if value is None:
            return None
        encryptor = get_data_encryptor()
        if isinstance(value, str) and value.startswith(_VERSION_PREFIX):
            try:
                ciphertext = _decode_ciphertext(value)
                plaintext = encryptor.decrypt(ciphertext, aad=self._aad)
                return self._deserializer(plaintext)
            except Exception:
                logger.exception(
                    "Failed to decrypt encrypted column '%s' with prefix %s",
                    self._label,
                    _VERSION_PREFIX,
                )
                return None

        # Legacy plaintext fallback. Return as-is but log a warning so operators
        # can schedule a backfill.
        if not self._legacy_warned:
            logger.warning(
                "Returning legacy plaintext value for encrypted column '%s'. "
                "Schedule a backfill to encrypt existing rows.",
                self._label,
            )
            self._legacy_warned = True

        return value


class EncryptedTextType(_EncryptedBase):
    def __init__(self, column_label: str) -> None:
        super().__init__(
            column_label=column_label,
            serializer=lambda value: value.encode("utf-8"),
            deserializer=lambda payload: payload.decode("utf-8"),
        )


class EncryptedJSONType(_EncryptedBase):
    def __init__(self, column_label: str) -> None:
        super().__init__(
            column_label=column_label,
            serializer=lambda value: json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
            deserializer=lambda payload: json.loads(payload.decode("utf-8")),
        )

