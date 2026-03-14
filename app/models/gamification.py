"""Database models for the gamification subsystem.

Tables
------
- UserXP: per-user XP totals and current level
- UserBadge: per-user badge progress and unlock state
- GamificationEvent: audit log of all domain events
- RewardLog: audit log of variable rewards granted
- UserSkillXP: per-user per-skill-category XP
- UserQuest: 90-day personal growth quest
- AccountabilityPact: habit commitment contracts
- Circle / CircleMember: group accountability circles
"""
from __future__ import annotations

from datetime import datetime, timezone, date
from typing import Optional, TYPE_CHECKING

from sqlalchemy import Column, DateTime, Text, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from ..security.encrypted_types import EncryptedTextType, EncryptedJSONType

if TYPE_CHECKING:
    from .users import User
    from .habit import Habit


# ─── XP & Leveling ───────────────────────────────────────────────
class UserXP(SQLModel, table=True):
    """Tracks a user's total XP and computed level."""
    __tablename__ = "user_xp"
    __table_args__ = (UniqueConstraint("user_id", name="uq_user_xp_user"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="users.id")
    total_xp: int = Field(default=0)
    level: str = Field(default="Beginner", max_length=50)
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)


# ─── Badges ──────────────────────────────────────────────────────
class UserBadge(SQLModel, table=True):
    """Per-user badge progress.  One row per (user, badge_id) pair."""
    __tablename__ = "user_badges"
    __table_args__ = (
        UniqueConstraint("user_id", "badge_id", name="uq_user_badge"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="users.id")
    badge_id: str = Field(max_length=100, index=True)
    progress: int = Field(default=0)
    unlocked: bool = Field(default=False)
    unlocked_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


# ─── Domain Event Audit Log ──────────────────────────────────────
class GamificationEvent(SQLModel, table=True):
    """Immutable audit log of every domain event passing through the bus."""
    __tablename__ = "gamification_events"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="users.id")
    event_type: str = Field(max_length=100, index=True)
    feature_id: str = Field(default="", max_length=20)
    properties_json: Optional[dict] = Field(
        default=None,
        sa_column=Column(EncryptedJSONType("gamification_events.properties")),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )


# ─── Variable Reward Audit Log ───────────────────────────────────
class RewardLog(SQLModel, table=True):
    """Records every reward granted (for fairness auditing and pity timer)."""
    __tablename__ = "reward_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="users.id")
    reward_type: str = Field(max_length=50)
    reward_tier: str = Field(max_length=20)
    properties_json: Optional[dict] = Field(
        default=None,
        sa_column=Column(EncryptedJSONType("reward_logs.properties")),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


# ─── Per-Skill XP ────────────────────────────────────────────────
class UserSkillXP(SQLModel, table=True):
    """Tracks XP per skill category (productivity, habits, etc.)."""
    __tablename__ = "user_skill_xp"
    __table_args__ = (
        UniqueConstraint("user_id", "skill_category", name="uq_user_skill_category"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="users.id")
    skill_category: str = Field(max_length=50)
    xp: int = Field(default=0)
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)


# ─── Personal Growth Quest ───────────────────────────────────────
class UserQuest(SQLModel, table=True):
    """A user's 90-day personal growth quest."""
    __tablename__ = "user_quests"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="users.id")
    quest_text: str = Field(
        sa_column=Column(EncryptedTextType("user_quests.quest_text"), nullable=False),
    )
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    target_date: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    completed_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    active: bool = Field(default=True, index=True)


# ─── Accountability Pact ─────────────────────────────────────────
class AccountabilityPact(SQLModel, table=True):
    """A commitment contract on a habit with self-chosen consequences."""
    __tablename__ = "accountability_pacts"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="users.id")
    habit_id: int = Field(index=True, foreign_key="habits.id")
    consequence_type: str = Field(max_length=50)  # stern_message | strict_coach_24h | scorecard_note
    threshold_days: int = Field(default=3)  # consecutive misses before trigger
    active: bool = Field(default=True, index=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    def touch(self) -> None:
        self.active = not self.active


# ─── Group Accountability Circles ────────────────────────────────
class Circle(SQLModel, table=True):
    """A group accountability circle (3-5 members)."""
    __tablename__ = "circles"
    __table_args__ = (
        UniqueConstraint("group_chat_id", name="uq_circle_group_chat"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    group_chat_id: int = Field(index=True)
    name: str = Field(max_length=200)
    created_by: int = Field(foreign_key="users.id")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class CircleMember(SQLModel, table=True):
    """Membership record for an accountability circle."""
    __tablename__ = "circle_members"
    __table_args__ = (
        UniqueConstraint("circle_id", "user_id", name="uq_circle_member"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    circle_id: int = Field(index=True, foreign_key="circles.id")
    user_id: int = Field(index=True, foreign_key="users.id")
    anonymous: bool = Field(default=False)
    joined_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
