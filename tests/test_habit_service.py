import pytest
from datetime import date, timedelta
from app.services.habit_service import HabitService

@pytest.mark.asyncio
async def test_habit_streak(db_session):
    # Create habit
    habit = await HabitService.create_habit(
        db_session,
        user_id=1,
        name="Test Habit",
        cadence="daily"
    )
    
    # Log today
    today = date.today()
    await HabitService.log_habit(db_session, habit.id, today)
    await db_session.commit()
    
    # Refresh
    await db_session.refresh(habit)
    assert habit.current_streak == 1
    
    # Log yesterday (should continue streak)
    yesterday = today - timedelta(days=1)
    await HabitService.log_habit(db_session, habit.id, yesterday)
    await db_session.commit()
    
    await db_session.refresh(habit)
    assert habit.current_streak == 2