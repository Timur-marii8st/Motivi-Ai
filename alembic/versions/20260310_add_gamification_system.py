"""Add gamification system tables and columns.

Creates: user_xp, user_badges, gamification_events, reward_logs,
         user_skill_xp, user_quests, accountability_pacts,
         circles, circle_members.

Adds columns to: users (streak, referral, milestone),
                 user_settings (leaderboard, persona),
                 core_facts (category).

Revision ID: 20260310_add_gamification_system
Revises: 20260301_add_userbot_session_and_settings
Create Date: 2026-03-10 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260310_add_gamification_system"
down_revision: Union[str, Sequence[str], None] = "20260301_add_userbot_session_and_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create gamification tables and add new columns."""

    # ── New columns on users ──────────────────────────────────
    op.add_column("users", sa.Column("streak_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("users", sa.Column("streak_freeze_tokens", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("users", sa.Column("last_active_date", sa.Date(), nullable=True))
    op.add_column("users", sa.Column("referral_code", sa.String(32), nullable=True))
    op.add_column("users", sa.Column("referred_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True))
    op.add_column("users", sa.Column("last_memory_milestone", sa.Integer(), nullable=False, server_default="0"))
    op.create_index("ix_users_last_active_date", "users", ["last_active_date"])
    op.create_index("ix_users_referral_code", "users", ["referral_code"], unique=True)

    # ── New columns on user_settings ──────────────────────────
    op.add_column("user_settings", sa.Column("show_on_leaderboard", sa.Boolean(), nullable=False, server_default="true"))
    op.add_column("user_settings", sa.Column("hide_streak", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("user_settings", sa.Column("persona_preferences_json", sa.Text(), nullable=True))

    # ── New column on core_facts ──────────────────────────────
    op.add_column("core_facts", sa.Column("category", sa.String(50), nullable=True))
    op.create_index("ix_core_facts_category", "core_facts", ["category"])

    # ── user_xp ──────────────────────────────────────────────
    op.create_table(
        "user_xp",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("total_xp", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("level", sa.String(50), nullable=False, server_default="'Beginner'"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("user_id", name="uq_user_xp_user"),
    )
    op.create_index("ix_user_xp_user_id", "user_xp", ["user_id"])

    # ── user_badges ──────────────────────────────────────────
    op.create_table(
        "user_badges",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("badge_id", sa.String(100), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unlocked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("unlocked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("user_id", "badge_id", name="uq_user_badge"),
    )
    op.create_index("ix_user_badges_user_id", "user_badges", ["user_id"])
    op.create_index("ix_user_badges_badge_id", "user_badges", ["badge_id"])

    # ── gamification_events ──────────────────────────────────
    op.create_table(
        "gamification_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("feature_id", sa.String(20), nullable=False, server_default="''"),
        sa.Column("properties_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_gamification_events_user_id", "gamification_events", ["user_id"])
    op.create_index("ix_gamification_events_event_type", "gamification_events", ["event_type"])
    op.create_index("ix_gamification_events_created_at", "gamification_events", ["created_at"])

    # ── reward_logs ──────────────────────────────────────────
    op.create_table(
        "reward_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reward_type", sa.String(50), nullable=False),
        sa.Column("reward_tier", sa.String(20), nullable=False),
        sa.Column("properties_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_reward_logs_user_id", "reward_logs", ["user_id"])

    # ── user_skill_xp ────────────────────────────────────────
    op.create_table(
        "user_skill_xp",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("skill_category", sa.String(50), nullable=False),
        sa.Column("xp", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("user_id", "skill_category", name="uq_user_skill_category"),
    )
    op.create_index("ix_user_skill_xp_user_id", "user_skill_xp", ["user_id"])

    # ── user_quests ──────────────────────────────────────────
    op.create_table(
        "user_quests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("quest_text", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("target_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.create_index("ix_user_quests_user_id", "user_quests", ["user_id"])
    op.create_index("ix_user_quests_active", "user_quests", ["active"])

    # ── accountability_pacts ─────────────────────────────────
    op.create_table(
        "accountability_pacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("habit_id", sa.Integer(), sa.ForeignKey("habits.id"), nullable=False),
        sa.Column("consequence_type", sa.String(50), nullable=False),
        sa.Column("threshold_days", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_accountability_pacts_user_id", "accountability_pacts", ["user_id"])
    op.create_index("ix_accountability_pacts_habit_id", "accountability_pacts", ["habit_id"])
    op.create_index("ix_accountability_pacts_active", "accountability_pacts", ["active"])

    # ── circles ──────────────────────────────────────────────
    op.create_table(
        "circles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("group_chat_id", name="uq_circle_group_chat"),
    )
    op.create_index("ix_circles_group_chat_id", "circles", ["group_chat_id"])

    # ── circle_members ───────────────────────────────────────
    op.create_table(
        "circle_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("circle_id", sa.Integer(), sa.ForeignKey("circles.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("anonymous", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("circle_id", "user_id", name="uq_circle_member"),
    )
    op.create_index("ix_circle_members_circle_id", "circle_members", ["circle_id"])
    op.create_index("ix_circle_members_user_id", "circle_members", ["user_id"])


def downgrade() -> None:
    """Drop gamification tables and remove new columns."""
    # Drop tables in reverse dependency order
    op.drop_table("circle_members")
    op.drop_table("circles")
    op.drop_table("accountability_pacts")
    op.drop_table("user_quests")
    op.drop_table("user_skill_xp")
    op.drop_table("reward_logs")
    op.drop_table("gamification_events")
    op.drop_table("user_badges")
    op.drop_table("user_xp")

    # Remove columns from core_facts
    op.drop_index("ix_core_facts_category", "core_facts")
    op.drop_column("core_facts", "category")

    # Remove columns from user_settings
    op.drop_column("user_settings", "persona_preferences_json")
    op.drop_column("user_settings", "hide_streak")
    op.drop_column("user_settings", "show_on_leaderboard")

    # Remove columns from users
    op.drop_index("ix_users_referral_code", "users")
    op.drop_index("ix_users_last_active_date", "users")
    op.drop_column("users", "last_memory_milestone")
    op.drop_column("users", "referred_by")
    op.drop_column("users", "referral_code")
    op.drop_column("users", "last_active_date")
    op.drop_column("users", "streak_freeze_tokens")
    op.drop_column("users", "streak_count")
