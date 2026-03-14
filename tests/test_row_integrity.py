from __future__ import annotations

import pytest

from app.security import row_integrity as ri


class _Dummy:
    __tablename__ = "dummy_table"

    def __init__(self, owner_id: int | None, payload: str, integrity_sig: str | None = None):
        self.id = 1
        self.owner_id = owner_id
        self.payload = payload
        self.integrity_sig = integrity_sig


def _setup_dummy_tracking(monkeypatch):
    monkeypatch.setattr(
        ri,
        "_TRACKED_MODELS",
        {_Dummy: (lambda obj: obj.owner_id, ("payload",))},
    )


def test_integrity_strict_mode_rejects_missing_signature(monkeypatch):
    _setup_dummy_tracking(monkeypatch)
    monkeypatch.setattr(ri.settings, "INTEGRITY_STRICT_MODE", True)

    obj = _Dummy(owner_id=7, payload="secret", integrity_sig=None)
    with pytest.raises(RuntimeError, match="Missing integrity signature"):
        ri._verify_instance(obj)


def test_integrity_non_strict_allows_missing_signature(monkeypatch):
    _setup_dummy_tracking(monkeypatch)
    monkeypatch.setattr(ri.settings, "INTEGRITY_STRICT_MODE", False)

    obj = _Dummy(owner_id=7, payload="secret", integrity_sig=None)
    # Should not raise in non-strict mode
    ri._verify_instance(obj)


def test_integrity_detects_ciphertext_swap_like_tampering(monkeypatch):
    _setup_dummy_tracking(monkeypatch)
    monkeypatch.setattr(ri.settings, "INTEGRITY_STRICT_MODE", True)

    obj = _Dummy(owner_id=7, payload="secret")
    ri.recalculate_integrity_signature(obj)

    # Simulate tampering: move encrypted payload to another owner row
    obj.owner_id = 8
    with pytest.raises(RuntimeError, match="Integrity check failed"):
        ri._verify_instance(obj)


def test_integrity_valid_signature_passes(monkeypatch):
    _setup_dummy_tracking(monkeypatch)
    monkeypatch.setattr(ri.settings, "INTEGRITY_STRICT_MODE", True)

    obj = _Dummy(owner_id=7, payload="secret")
    ri.recalculate_integrity_signature(obj)
    ri._verify_instance(obj)
