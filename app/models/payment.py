from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, Column, DateTime, Integer, String, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel


if TYPE_CHECKING:
    from .users import User


class Payment(SQLModel, table=True):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint(
            "telegram_payment_charge_id",
            name="uq_payments_telegram_payment_charge_id",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="users.id")
    user: "User" = Relationship(back_populates="payments")

    invoice_payload: str = Field(max_length=255, index=True)
    currency: str = Field(max_length=10)
    total_amount: int = Field(sa_column=Column(Integer, nullable=False))
    subscription_months: int = Field(default=1, sa_column=Column(Integer, nullable=False))

    telegram_payment_charge_id: str = Field(
        sa_column=Column(String(255), nullable=False, index=True),
    )
    provider_payment_charge_id: Optional[str] = Field(
        default=None,
        sa_column=Column(String(255), nullable=True),
    )
    subscription_expiration_date: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True, index=True),
    )
    is_recurring: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, default=False),
    )
    is_first_recurring: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, default=False),
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
