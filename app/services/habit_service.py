from __future__ import annotations
from typing import List, Optional
from datetime import date, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, and_, func
from loguru import logger

from ..models.habit import Habit, HabitLog

class HabitService:
    """
    CRUD and business logic for habits.
    """

    @staticmethod
    async def create_habit(
        session: AsyncSession,
        user_id: int,
        name: str,
        description: Optional[str] = None,
        cadence: str = "daily",
        target_count: int = 1,
        reminder_time: Optional[str] = None,
    ) -> Habit:
        """Create a new habit."""
        from datetime import time
        reminder_t = None
        if reminder_time:
            try:
                reminder_t = time.fromisoformat(reminder_time)
            except ValueError as e:
                logger.warning("Invalid reminder_time format '{}',  for user {}: {}", reminder_time, user_id, e)
                raise ValueError("reminder_time must be in HH:MM format")
        
        habit = Habit(
            user_id=user_id,
            name=name,
            description=description,
            cadence=cadence,
            target_count=target_count,
            reminder_time=reminder_t,
        )
        session.add(habit)
        await session.flush()
        logger.info("Created habit {} for user {}", habit.id, user_id)
        return habit

    @staticmethod
    async def list_habits(session: AsyncSession, user_id: int, active_only: bool = True) -> List[Habit]:
        """List user's habits."""
        filters = [Habit.user_id == user_id]
        if active_only:
            filters.append(Habit.active == True)
        
        result = await session.execute(select(Habit).where(and_(*filters)).order_by(Habit.created_at))
        return list(result.scalars().all())

    @staticmethod
    async def log_habit(
        session: AsyncSession,
        habit_id: int,
        log_date: date,
        count: int = 1,
        note: Optional[str] = None,
    ) -> HabitLog:
        """
        Log a habit completion and update streak.
        """
        habit = await session.get(Habit, habit_id)
        if not habit:
            raise ValueError(f"Habit {habit_id} not found")
        
        # Check if already logged for the given date
        result = await session.execute(
            select(HabitLog).where(
                HabitLog.habit_id == habit_id,
                HabitLog.log_date == log_date,
            )
        )
        existing_log = result.scalar_one_or_none()
        
        if existing_log:
            existing_log.count += count
            if note:
                existing_log.note = note
            log = existing_log
        else:
            log = HabitLog(habit_id=habit_id, log_date=log_date, count=count, note=note)
            session.add(log)
        
        await session.flush()
        
        # Update streak by recalculating from all logs
        await HabitService._update_streak(session, habit)
        
        logger.info("Logged habit {} on {}", habit_id, log_date)
        return log

    @staticmethod
    async def _update_streak(session: AsyncSession, habit: Habit):
        """
        Recalculates the current and longest streak based on all historical logs.
        This method is stateless and correct regardless of logging order.
        """
        # Query all unique log dates for this habit, in descending order
        result = await session.execute(
            select(HabitLog.log_date)
            .where(HabitLog.habit_id == habit.id)
            .distinct()
            .order_by(HabitLog.log_date.desc())
        )
        log_dates = result.scalars().all()

        if not log_dates:
            habit.current_streak = 0
            habit.last_completed_date = None
        else:
            # Dispatch to the correct calculation logic based on cadence
            if habit.cadence == "daily":
                streak = HabitService._calculate_daily_streak(log_dates)
            elif habit.cadence == "weekly":
                streak = HabitService._calculate_weekly_streak(log_dates)
            else:
                # For unsupported cadences, log a warning and avoid changing the streak
                logger.warning("Streak calculation for cadence '{}' is not implemented.", habit.cadence)
                streak = habit.current_streak

            habit.current_streak = streak
            habit.last_completed_date = log_dates[0]  # The most recent log date
            if habit.current_streak > habit.longest_streak:
                habit.longest_streak = habit.current_streak
        
        habit.touch()
        session.add(habit)
        await session.flush()

    @staticmethod
    def _calculate_daily_streak(log_dates: List[date]) -> int:
        """Calculates a daily streak from a sorted list of unique dates."""
        streak = 0
        # Start from the most recent log date
        expected_date = log_dates[0]
        
        for log_date in log_dates:
            if log_date == expected_date:
                streak += 1
                expected_date -= timedelta(days=1)
            else:
                # A gap in the dates was found, so the streak is broken
                break
        return streak

    @staticmethod
    def _calculate_weekly_streak(log_dates: List[date]) -> int:
        if not log_dates:
            return 0

        log_dates.sort(reverse=True) # Sort descending
        streak = 0
        if log_dates:
            current_year, current_week, _ = log_dates[0].isocalendar()
            streak = 1

            for i in range(1, len(log_dates)):
                prev_year, prev_week, _ = log_dates[i].isocalendar()
                if (prev_year == current_year and prev_week == current_week -1) or \
                    (prev_year == current_year -1 and current_week == 1 and prev_week == 52): # handles end of year.
                        streak += 1
                        current_year, current_week = prev_year, prev_week
                else:
                    break
        return streak

    @staticmethod
    async def get_habit_stats(session: AsyncSession, habit_id: int) -> dict:
        """
        Get statistics for a habit.
        """
        habit = await session.get(Habit, habit_id)
        if not habit:
            return {}
        
        # Total logs
        result = await session.execute(
            select(func.count(HabitLog.id), func.sum(HabitLog.count))
            .where(HabitLog.habit_id == habit_id)
        )
        row = result.one()
        total_logs = row[0] or 0
        total_count = row[1] or 0
        
        return {
            "habit_id": habit.id,
            "name": habit.name,
            "current_streak": habit.current_streak,
            "longest_streak": habit.longest_streak,
            "total_logs": total_logs,
            "total_count": total_count,
            "last_completed": habit.last_completed_date.isoformat() if habit.last_completed_date else None,
        }

    @staticmethod
    async def archive_habit(session: AsyncSession, habit_id: int):
        """Archive (deactivate) a habit."""
        habit = await session.get(Habit, habit_id)
        if habit:
            habit.active = False
            habit.touch()
            session.add(habit)
            await session.flush()
            logger.info("Archived habit {}", habit_id)