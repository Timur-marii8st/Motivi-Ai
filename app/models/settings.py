from typing import Optional, TYPE_CHECKING
from datetime import datetime, timezone, time
from sqlmodel import SQLModel, Field, Column, JSON, UniqueConstraint, Relationship
from sqlalchemy import DateTime


if TYPE_CHECKING:
    from .users import User

class UserSettings(SQLModel, table=True):
    """
    User preferences for notifications, proactivity, and break mode.
    """
    __tablename__ = "user_settings"
    __table_args__ = (UniqueConstraint("user_id", name="uq_user_settings_user"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="users.id")
    user: "User" = Relationship(back_populates="settings")

    # Notification windows (can override user wake/bed times for messaging)
    morning_window_start: Optional[time] = None  # If None, use user.wake_time
    morning_window_end: Optional[time] = None    # E.g., wake + 2 hours
    evening_window_start: Optional[time] = None  # E.g., bed - 2 hours
    evening_window_end: Optional[time] = None    # If None, use user.bed_time

    # Break mode
    break_mode_active: bool = Field(default=False)
    break_mode_until: Optional[datetime] = Field(default=None, index=True)

    # Proactivity toggles
    enable_morning_checkin: bool = Field(default=True)
    enable_evening_wrapup: bool = Field(default=True)
    enable_weekly_plan: bool = Field(default=True)
    enable_monthly_plan: bool = Field(default=True)

    # Summary content preferences
    summary_preferences_json: Optional[dict] = Field(
        default=None, sa_column=Column(JSON)
    )  # e.g., {"include_habits": true, "include_calendar": true}

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)