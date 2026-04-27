from __future__ import annotations

from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.types import LabeledPrice, Message, PreCheckoutQuery
from loguru import logger
from redis.asyncio import Redis

from ...config import settings
from ...db import AsyncSessionLocal
from ...services.profile_services import get_or_create_user
from ...services.subscription_service import SubscriptionService

router = Router(name="subscription")


@router.message(F.text == "/subscribe")
async def cmd_subscribe(message: Message, session) -> None:
    user = await get_or_create_user(session, message.from_user.id, message.chat.id)
    status = await SubscriptionService.get_user_status(user)

    if user.is_premium:
        await message.answer(
            (
                "<b>Motivi Premium already active</b>\n\n"
                f"Valid until: {user.subscription_ends_at.strftime('%d.%m.%Y')}\n"
                "A new purchase is blocked while Premium is active to avoid creating "
                "a second parallel auto-renewing subscription."
            )
        )
        return

    text = "<b>Motivi Premium</b>\n\n"
    if status == "trial":
        days_left = settings.TRIAL_DAYS - (
            datetime.now(timezone.utc) - user.created_at
        ).days
        text += f"Status: <b>TRIAL</b>\nDays left: {max(0, days_left)}\n\n"
    else:
        text += "Status: <b>EXPIRED</b>\n\n"

    text += (
        "<b>Benefits:</b>\n"
        f"- {settings.LIMIT_DAILY_PREMIUM} messages/day instead of {settings.LIMIT_DAILY_TRIAL}\n"
        "- Full access to memory-powered features\n"
        "- Priority support\n\n"
        f"<b>Price: {settings.SUBSCRIPTION_PRICE_STARS} XTR every 30 days</b>"
    )

    await message.answer(text)
    await message.answer_invoice(
        title="Motivi Premium (30 days)",
        description="Full access to Motivi Premium features",
        payload=SubscriptionService.build_invoice_payload(user.id),
        provider_token="",
        currency="XTR",
        prices=[
            LabeledPrice(
                label="Motivi Premium",
                amount=settings.SUBSCRIPTION_PRICE_STARS,
            )
        ],
        start_parameter="subscribe",
        subscription_period=SubscriptionService.SUBSCRIPTION_PERIOD_SECONDS,
    )


@router.pre_checkout_query()
async def pre_checkout_handler(query: PreCheckoutQuery) -> None:
    async with AsyncSessionLocal() as session:
        user = await SubscriptionService.get_user_by_telegram_id(
            session, query.from_user.id
        )
        if user is None:
            await query.answer(
                ok=False,
                error_message="User profile not found. Open /start and try again.",
            )
            return

        if user.is_premium:
            await query.answer(
                ok=False,
                error_message=(
                    "Premium is already active. A second parallel subscription is blocked."
                ),
            )
            return

        is_valid, error, _invoice = SubscriptionService.validate_subscription_payment(
            payload=query.invoice_payload,
            currency=query.currency,
            total_amount=query.total_amount,
            user=user,
        )
        if not is_valid:
            logger.warning(
                "Rejected pre-checkout for tg_user_id={} reason={} payload={} currency={} amount={}",
                query.from_user.id,
                error,
                query.invoice_payload,
                query.currency,
                query.total_amount,
            )
            await query.answer(
                ok=False,
                error_message="Payment validation failed. Please retry with /subscribe.",
            )
            return

    await query.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment_handler(message: Message, session) -> None:
    payment = message.successful_payment
    user = await get_or_create_user(session, message.from_user.id, message.chat.id)

    is_valid, error, invoice = SubscriptionService.validate_subscription_payment(
        payload=payment.invoice_payload,
        currency=payment.currency,
        total_amount=payment.total_amount,
        user=user,
    )
    if not is_valid or invoice is None:
        logger.error(
            "Invalid successful payment ignored for user_id={} reason={} payload={} currency={} amount={} charge_id={}",
            user.id,
            error,
            payment.invoice_payload,
            payment.currency,
            payment.total_amount,
            payment.telegram_payment_charge_id,
        )
        await message.answer(
            "Payment was received, but automatic activation failed validation. "
            "Please contact support and attach the Telegram receipt."
        )
        return

    was_recorded = await SubscriptionService.record_payment(
        session,
        user_id=user.id,
        payload=payment.invoice_payload,
        currency=payment.currency,
        total_amount=payment.total_amount,
        months=invoice.months,
        telegram_payment_charge_id=payment.telegram_payment_charge_id,
        provider_payment_charge_id=payment.provider_payment_charge_id,
        subscription_expiration_date=payment.subscription_expiration_date,
        is_recurring=bool(payment.is_recurring),
        is_first_recurring=bool(payment.is_first_recurring),
    )
    if not was_recorded:
        await message.answer("This payment was already processed earlier.")
        return

    logger.info(
        "Payment received: amount={} currency={} user_id={} charge_id={} recurring={} first_recurring={}",
        payment.total_amount,
        payment.currency,
        user.id,
        payment.telegram_payment_charge_id,
        bool(payment.is_recurring),
        bool(payment.is_first_recurring),
    )

    await SubscriptionService.add_subscription_time(session, user, months=invoice.months)
    await session.commit()

    try:
        redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        await redis.delete(f"sub_cache:{message.from_user.id}")
        await redis.aclose()
    except Exception as exc:
        logger.warning("Failed to invalidate sub cache for user {}: {}", user.id, exc)

    await message.answer(
        (
            "<b>Payment successful.</b>\n\n"
            f"Premium is now active. Your new daily limit is {settings.LIMIT_DAILY_PREMIUM} messages."
        )
    )
