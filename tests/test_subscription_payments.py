from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.bot.routers import subscription as subscription_router
from app.services.subscription_service import SubscriptionService


class _AsyncSessionContext:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _run(coro):
    return asyncio.run(coro)


def _make_user(*, user_id: int = 7, tg_user_id: int = 77, premium: bool = False):
    now = datetime.now(timezone.utc)
    subscription_ends_at = now + timedelta(days=5) if premium else None
    return SimpleNamespace(
        id=user_id,
        tg_user_id=tg_user_id,
        created_at=now - timedelta(days=1),
        subscription_ends_at=subscription_ends_at,
        is_premium=premium,
        is_trial=not premium,
        touch=lambda: None,
    )


def test_parse_invoice_payload_accepts_new_and_legacy_formats():
    new_payload = SubscriptionService.parse_invoice_payload("sub:7:1")
    old_payload = SubscriptionService.parse_invoice_payload("sub_7_1m")

    assert new_payload == old_payload
    assert new_payload.user_id == 7
    assert new_payload.months == 1


def test_validate_subscription_payment_rejects_mismatch_amount_and_currency():
    user = _make_user(user_id=7)

    ok, error, _ = SubscriptionService.validate_subscription_payment(
        payload="sub:8:1",
        currency="XTR",
        total_amount=SubscriptionService.expected_amount(1),
        user=user,
    )
    assert (ok, error) == (False, "invoice_user_mismatch")

    ok, error, _ = SubscriptionService.validate_subscription_payment(
        payload="sub:7:1",
        currency="USD",
        total_amount=SubscriptionService.expected_amount(1),
        user=user,
    )
    assert (ok, error) == (False, "invalid_currency")

    ok, error, _ = SubscriptionService.validate_subscription_payment(
        payload="sub:7:1",
        currency="XTR",
        total_amount=999,
        user=user,
    )
    assert (ok, error) == (False, "invalid_amount")


def test_cmd_subscribe_blocks_second_parallel_subscription(monkeypatch):
    user = _make_user(premium=True)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=user.tg_user_id),
        chat=SimpleNamespace(id=555),
        answer=AsyncMock(),
        answer_invoice=AsyncMock(),
    )

    async def fake_get_or_create_user(session, tg_user_id, chat_id):
        return user

    monkeypatch.setattr(subscription_router, "get_or_create_user", fake_get_or_create_user)

    _run(subscription_router.cmd_subscribe(message, session=object()))

    message.answer.assert_awaited_once()
    message.answer_invoice.assert_not_called()


def test_pre_checkout_handler_rejects_invalid_payment(monkeypatch):
    user = _make_user()
    query = SimpleNamespace(
        from_user=SimpleNamespace(id=user.tg_user_id),
        invoice_payload="sub:7:1",
        currency="XTR",
        total_amount=999,
        answer=AsyncMock(),
    )

    fake_session = object()
    monkeypatch.setattr(
        subscription_router,
        "AsyncSessionLocal",
        lambda: _AsyncSessionContext(fake_session),
    )

    async def fake_get_user_by_telegram_id(session, tg_user_id):
        assert session is fake_session
        return user

    monkeypatch.setattr(
        SubscriptionService,
        "get_user_by_telegram_id",
        fake_get_user_by_telegram_id,
    )

    _run(subscription_router.pre_checkout_handler(query))

    query.answer.assert_awaited_once()
    assert query.answer.await_args.kwargs["ok"] is False


def test_successful_payment_handler_is_idempotent(monkeypatch):
    user = _make_user()
    payment = SimpleNamespace(
        invoice_payload="sub:7:1",
        currency="XTR",
        total_amount=SubscriptionService.expected_amount(1),
        telegram_payment_charge_id="charge-1",
        provider_payment_charge_id="provider-1",
        subscription_expiration_date=None,
        is_recurring=True,
        is_first_recurring=True,
    )
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=user.tg_user_id),
        chat=SimpleNamespace(id=555),
        successful_payment=payment,
        answer=AsyncMock(),
    )
    session = SimpleNamespace(commit=AsyncMock())

    async def fake_get_or_create_user(db_session, tg_user_id, chat_id):
        return user

    async def fake_record_payment(*args, **kwargs):
        return False

    add_subscription_time = AsyncMock()

    monkeypatch.setattr(subscription_router, "get_or_create_user", fake_get_or_create_user)
    monkeypatch.setattr(SubscriptionService, "record_payment", fake_record_payment)
    monkeypatch.setattr(SubscriptionService, "add_subscription_time", add_subscription_time)

    _run(subscription_router.successful_payment_handler(message, session))

    add_subscription_time.assert_not_called()
    session.commit.assert_not_called()
    message.answer.assert_awaited_once()
    assert "already processed" in message.answer.await_args.args[0]
