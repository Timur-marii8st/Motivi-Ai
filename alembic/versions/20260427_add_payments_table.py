"""add_payments_table

Create a payments table for Telegram payment audit trail and idempotency.

Revision ID: 20260427_add_payments_table
Revises: 20260314_add_userbot_reply_approval
Create Date: 2026-04-27 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260427_add_payments_table"
down_revision: Union[str, Sequence[str], None] = "20260314_add_userbot_reply_approval"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("invoice_payload", sa.String(length=255), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("total_amount", sa.Integer(), nullable=False),
        sa.Column("subscription_months", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("telegram_payment_charge_id", sa.String(length=255), nullable=False),
        sa.Column("provider_payment_charge_id", sa.String(length=255), nullable=True),
        sa.Column("subscription_expiration_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_recurring", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_first_recurring", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "telegram_payment_charge_id",
            name="uq_payments_telegram_payment_charge_id",
        ),
    )
    op.create_index("ix_payments_user_id", "payments", ["user_id"])
    op.create_index("ix_payments_invoice_payload", "payments", ["invoice_payload"])
    op.create_index(
        "ix_payments_subscription_expiration_date",
        "payments",
        ["subscription_expiration_date"],
    )
    op.create_index(
        "ix_payments_telegram_payment_charge_id",
        "payments",
        ["telegram_payment_charge_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_payments_telegram_payment_charge_id", table_name="payments")
    op.drop_index("ix_payments_subscription_expiration_date", table_name="payments")
    op.drop_index("ix_payments_invoice_payload", table_name="payments")
    op.drop_index("ix_payments_user_id", table_name="payments")
    op.drop_table("payments")
