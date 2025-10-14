from typing import Optional, TYPE_CHECKING
from datetime import datetime, date
from sqlmodel import SQLModel, Field, Column, JSON, UniqueConstraint, Relationship


if TYPE_CHECKING:
    from .users import User

class WorkingMemory(SQLModel, table=True):
    """
    Short-term context: recent goals, events, summary.
    Refreshed weekly; decays after `decay_date`.
    """
    __tablename__ = "working_memory"
    __table_args__ = (UniqueConstraint("user_id", name="uq_working_memory_user"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="users.id")

    focus_summary: Optional[str] = Field(default=None, max_length=2000)
    short_term_goals_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))

    decay_date: Optional[date] = Field(default=None, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    user: "User" = Relationship(back_populates="working_memory")