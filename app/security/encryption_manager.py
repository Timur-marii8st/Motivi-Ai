from __future__ import annotations

import base64
import json
from typing import Optional

from loguru import logger
from tink import aead, cleartext_keyset_handle, JsonKeysetReader, TinkError

from ..config import settings


class DataEncryptionManager:
    """
    Centralized AEAD encryptor built on top of Google Tink.

    Uses a keyset provided via environment variable (base64-encoded JSON keyset).
    For production the keyset should be stored encrypted (e.g., in a KMS) and
    injected at runtime via secrets management.
    """

    def __init__(self, keyset_b64: str, *, keyset_label: str = "data"):
        if not keyset_b64:
            raise ValueError("DATA_ENCRYPTION_KEYSET_B64 must be configured.")

        aead.register()

        try:
            raw_keyset = base64.b64decode(keyset_b64.encode("utf-8"))
            keyset_json = raw_keyset.decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError("Failed to decode DATA_ENCRYPTION_KEYSET_B64") from exc

        try:
            reader = JsonKeysetReader(keyset_json)
            # NOTE: Using cleartext keyset handle. For production consider wrapping
            # the keyset with a KMS master key. This class keeps the interface small
            # so we can swap implementations later.
            handle = cleartext_keyset_handle.read(reader)
            self._primitive = handle.primitive(aead.Aead)
        except TinkError as exc:
            raise ValueError("Failed to initialize Tink AEAD primitive") from exc

        self._label = keyset_label

        logger.info("Initialized data encryption manager with keyset '%s'", self._label)

    def encrypt(self, data: bytes, *, aad: Optional[bytes] = None) -> bytes:
        if data is None:
            raise ValueError("Cannot encrypt None")
        try:
            return self._primitive.encrypt(data, aad or b"")
        except TinkError as exc:
            raise RuntimeError("AEAD encryption failed") from exc

    def decrypt(self, encrypted: bytes, *, aad: Optional[bytes] = None) -> bytes:
        if encrypted is None:
            raise ValueError("Cannot decrypt None")
        try:
            return self._primitive.decrypt(encrypted, aad or b"")
        except TinkError as exc:
            raise RuntimeError("AEAD decryption failed") from exc


_data_encryptor: DataEncryptionManager | None = None


def get_data_encryptor() -> DataEncryptionManager:
    global _data_encryptor
    if _data_encryptor is None:
        keyset_b64 = getattr(settings, "DATA_ENCRYPTION_KEYSET_B64", "")
        _data_encryptor = DataEncryptionManager(keyset_b64, keyset_label="primary")
    return _data_encryptor

