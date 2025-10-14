from typing import Optional, TYPE_CHECKING
from datetime import datetime, date, time
from sqlmodel import SQLModel, Field, Relationship


if TYPE_CHECKING:
    from .users import User

class Habit(SQLModel, table=True):
    """
    User habits with cadence, reminders, and streak tracking.
    """
    __tablename__ = "habits"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="users.id")
    user: "User" = Relationship(back_populates="habits")

    name: str = Field(max_length=200)
    description: Optional[str] = Field(default=None, max_length=1000)
    
    # Cadence: daily, weekly, custom
    cadence: str = Field(default="daily", max_length=20, index=True)
    target_count: int = Field(default=1)  # e.g., 1/day, 3/week
    
    # Reminder
    reminder_time: Optional[time] = None
    reminder_enabled: bool = Field(default=True)
    
    # Streak tracking
    current_streak: int = Field(default=0)
    longest_streak: int = Field(default=0)
    last_completed_date: Optional[date] = Field(default=None, index=True)
    
    # Metadata
    active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)

    def touch(self) -> None:
        self.updated_at = datetime.utcnow()


class HabitLog(SQLModel, table=True):
    """
    Logs of habit completions.
    """
    __tablename__ = "habit_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    habit_id: int = Field(index=True, foreign_key="habits.id")
    
    log_date: date = Field(index=True)
    count: int = Field(default=1)
    note: Optional[str] = Field(default=None, max_length=500)
    
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)