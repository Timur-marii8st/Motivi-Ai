from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from loguru import logger
from redis.asyncio import Redis
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ..config import settings
from ..models.payment import Payment
from ..models.users import User


@dataclass(frozen=True)
class SubscriptionInvoice:
    user_id: int
    months: int


class SubscriptionService:
    SUBSCRIPTION_PERIOD_SECONDS = 30 * 24 * 60 * 60
    DEFAULT_SUBSCRIPTION_MONTHS = 1

    @staticmethod
    async def get_user_status(user: User) -> str:
        if user.tg_user_id in settings.admin_ids:
            return "admin"
        if user.is_premium:
            return "premium"
        if user.is_trial:
            return "trial"
        return "expired"

    @staticmethod
    async def check_quota(user: User, redis: Redis) -> tuple[bool, str, int, int]:
        status = await SubscriptionService.get_user_status(user)

        if status == "admin":
            return True, status, 0, 999999
        if status == "premium":
            limit = settings.LIMIT_DAILY_PREMIUM
        elif status == "trial":
            limit = settings.LIMIT_DAILY_TRIAL
        else:
            limit = settings.LIMIT_DAILY_EXPIRED

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        key = f"quota:{user.id}:{today_str}"

        async with redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.execute_command("EXPIRE", key, 86400 + 3600, "NX")
            pipe_result = await pipe.execute()
        current_usage = int(pipe_result[0])

        if current_usage > limit:
            return False, status, current_usage, limit

        return True, status, current_usage, limit

    @staticmethod
    async def add_subscription_time(
        session: AsyncSession,
        user: User,
        months: int = DEFAULT_SUBSCRIPTION_MONTHS,
    ) -> None:
        now = datetime.now(timezone.utc)

        if user.subscription_ends_at and user.subscription_ends_at > now:
            start_date = user.subscription_ends_at
        else:
            start_date = now

        new_end_date = start_date + timedelta(days=30 * months)
        user.subscription_ends_at = new_end_date
        user.touch()
        session.add(user)
        logger.info("User {} subscription extended until {}", user.id, new_end_date)

    @staticmethod
    def build_invoice_payload(
        user_id: int,
        months: int = DEFAULT_SUBSCRIPTION_MONTHS,
    ) -> str:
        return f"sub:{user_id}:{months}"

    @staticmethod
    def parse_invoice_payload(payload: str) -> SubscriptionInvoice | None:
        if not payload:
            return None

        if payload.startswith("sub:"):
            parts = payload.split(":")
            if len(parts) != 3:
                return None
            _, user_id_str, months_str = parts
        elif payload.startswith("sub_") and payload.endswith("m"):
            parts = payload.split("_")
            if len(parts) != 3:
                return None
            _, user_id_str, months_token = parts
            months_str = months_token[:-1]
        else:
            return None

        try:
            user_id = int(user_id_str)
            months = int(months_str)
        except ValueError:
            return None

        if user_id <= 0 or months != SubscriptionService.DEFAULT_SUBSCRIPTION_MONTHS:
            return None

        return SubscriptionInvoice(user_id=user_id, months=months)

    @staticmethod
    def expected_amount(months: int) -> int:
        return settings.SUBSCRIPTION_PRICE_STARS * months

    @staticmethod
    def validate_subscription_payment(
        *,
        payload: str,
        currency: str,
        total_amount: int,
        user: User,
    ) -> tuple[bool, str | None, SubscriptionInvoice | None]:
        invoice = SubscriptionService.parse_invoice_payload(payload)
        if invoice is None:
            return False, "invalid_payload", None
        if invoice.user_id != user.id:
            return False, "invoice_user_mismatch", None
        if currency != "XTR":
            return False, "invalid_currency", None

        expected_amount = SubscriptionService.expected_amount(invoice.months)
        if total_amount != expected_amount:
            return False, "invalid_amount", None

        return True, None, invoice

    @staticmethod
    async def get_user_by_telegram_id(
        session: AsyncSession,
        tg_user_id: int,
    ) -> User | None:
        result = await session.execute(select(User).where(User.tg_user_id == tg_user_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def payment_already_processed(
        session: AsyncSession,
        telegram_payment_charge_id: str,
    ) -> bool:
        result = await session.execute(
            select(Payment.id).where(
                Payment.telegram_payment_charge_id == telegram_payment_charge_id
            )
        )
        return result.scalar_one_or_none() is not None

    @staticmethod
    async def record_payment(
        session: AsyncSession,
        *,
        user_id: int,
        payload: str,
        currency: str,
        total_amount: int,
        months: int,
        telegram_payment_charge_id: str,
        provider_payment_charge_id: str | None,
        subscription_expiration_date: datetime | None,
        is_recurring: bool,
        is_first_recurring: bool,
    ) -> bool:
        session.add(
            Payment(
                user_id=user_id,
                invoice_payload=payload,
                currency=currency,
                total_amount=total_amount,
                subscription_months=months,
                telegram_payment_charge_id=telegram_payment_charge_id,
                provider_payment_charge_id=provider_payment_charge_id,
                subscription_expiration_date=subscription_expiration_date,
                is_recurring=is_recurring,
                is_first_recurring=is_first_recurring,
            )
        )
        try:
            await session.flush()
            return True
        except IntegrityError:
            await session.rollback()
            logger.warning(
                "Duplicate payment ignored for charge_id={}",
                telegram_payment_charge_id,
            )
            return False
