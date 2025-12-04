from __future__ import annotations
from typing import Any, Dict
from datetime import datetime, timezone
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from ..mcp_client.client import MCPClient
from apscheduler.triggers.date import DateTrigger
from ..models.plan import Plan

class ToolExecutor:
    """
    Executes tool calls from LLM by routing to MCP server or local services.
    """
    def __init__(self, session: AsyncSession, mcp_client: MCPClient):
        self.session = session
        self.mcp = mcp_client

    async def execute(self, tool_name: str, args: Dict[str, Any], chat_id: int, user_id: int) -> Dict[str, Any]:
        """
        Route tool call to appropriate handler.
        """
        try:
            if tool_name == "schedule_reminder":
                return await self._schedule_reminder(args, chat_id, user_id)
            elif tool_name == "cancel_reminder":
                return await self._cancel_reminder(args, user_id)
            elif tool_name == "list_reminders":
                return await self._list_reminders(user_id)
            elif tool_name == "create_plan":
                return await self._create_plan(args, chat_id, user_id)
            elif tool_name == "check_plan":
                return await self._check_plan(user_id)
            elif tool_name == "edit_plan":
                return await self._edit_plan(args, chat_id, user_id)
            elif tool_name == "create_calendar_event":
                return await self._create_calendar_event(args, user_id)
            elif tool_name == "check_calendar_availability":
                return await self._check_availability(args, user_id)
            else:
                logger.warning("Unknown tool: {}", tool_name)
                return {"success": False, "error": "Unknown tool"}
        except Exception as e:
            logger.exception("Tool execution failed: {} - {}", tool_name, e)
            return {"success": False, "error": str(e)}

    async def _create_calendar_event(self, args: Dict, user_id: int) -> Dict:
        """Create calendar event."""
        from ..integrations.google_calendar import GoogleCalendarService
        from datetime import datetime
        
        start_dt = datetime.fromisoformat(args["start_datetime"])
        end_dt = datetime.fromisoformat(args["end_datetime"])
        
        event_id = await GoogleCalendarService.create_event(
            self.session,
            user_id,
            summary=args["summary"],
            start_dt=start_dt,
            end_dt=end_dt,
            description=args.get("description"),
        )
        
        if event_id:
            return {"success": True, "event_id": event_id}
        else:
            return {"success": False, "error": "Calendar not connected or API error"}

    async def _check_availability(self, args: Dict, user_id: int) -> Dict:
        """Check calendar availability."""
        from ..integrations.google_calendar import GoogleCalendarService
        from datetime import datetime, timezone
        
        start_dt = datetime.fromisoformat(args["start_datetime"])
        end_dt = datetime.fromisoformat(args["end_datetime"])
        
        available = await GoogleCalendarService.check_availability(
            self.session, user_id, start_dt, end_dt
        )
        
        return {"success": True, "available": available}

    async def _schedule_reminder(self, args: Dict, chat_id: int, user_id: int) -> Dict:
        """Schedule a one-off Telegram reminder for the user via APScheduler."""
        import uuid
        from datetime import datetime
        from pytz import utc as _utc
        from ..scheduler.scheduler_instance import scheduler, start_scheduler

        reminder_dt = datetime.fromisoformat(args["reminder_datetime_iso"])
        # Determine timezone to interpret the datetime if it's naive.
        # Priority: explicit args['timezone'] -> user's configured timezone -> UTC
        tzname = args.get("timezone")
        user_timezone = None
        if not tzname:
            try:
                from ..models.users import User
                result = await self.session.get(User, user_id)
                user_timezone = getattr(result, "user_timezone", None)
            except Exception:
                user_timezone = None

        if tzname is None and user_timezone:
            tzname = user_timezone

        # If reminder_dt is timezone-aware already, use it; otherwise localize
        from zoneinfo import ZoneInfo
        now_utc = datetime.now(_utc)
        if reminder_dt.tzinfo is None:
            if tzname:
                try:
                    reminder_dt = reminder_dt.replace(tzinfo=ZoneInfo(tzname))
                except Exception:
                    # Fall back to UTC if timezone name invalid
                    reminder_dt = reminder_dt.replace(tzinfo=_utc)
            else:
                reminder_dt = reminder_dt.replace(tzinfo=_utc)
        else:
            # Convert to UTC for consistency
                reminder_dt = reminder_dt.astimezone(_utc)

        # Do not allow scheduling reminders in the past
        if reminder_dt <= now_utc:
            logger.warning("Attempted to schedule reminder in the past: {} (now={})", reminder_dt, now_utc)
            return {"success": False, "error": "Cannot schedule a reminder in the past. Please provide a future UTC datetime."}

        # Generate unique job_id that includes user_id to avoid collisions
        unique_id = str(uuid.uuid4())[:8]
        job_id = f"reminder_{user_id}_{unique_id}"

        # Check if job already exists and remove it
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)

        from apscheduler.triggers.date import DateTrigger
        # Ensure the scheduler is running, so the job will execute
        try:
            if not scheduler.running:
                start_scheduler()
        except Exception:
            # If we cannot import or start scheduler, continue; job might be persisted for later worker
            logger.debug("Could not ensure scheduler was running when scheduling reminder")

        trigger = DateTrigger(run_date=reminder_dt, timezone=_utc)

        scheduler.add_job(
            func="app.scheduler.jobs:send_one_off_reminder_job",
            trigger=trigger,
            id=job_id,
            args=[user_id, chat_id, args["message_text"]],
            replace_existing=True,
        )

        logger.info("Scheduled one-off reminder for user {} at {} (job_id={})", user_id, reminder_dt, job_id)
        return {"success": True, "job_id": job_id}

    async def _cancel_reminder(self, args: Dict, user_id: int) -> Dict:
        """Cancel a scheduled reminder by job_id."""
        from ..scheduler.scheduler_instance import scheduler
        
        job_id = args["job_id"]
        
        # Validate that the job_id belongs to this user
        if not job_id.startswith(f"reminder_{user_id}_"):
            logger.warning("User {} attempted to cancel reminder from different user: {}", user_id, job_id)
            return {"success": False, "error": "Cannot cancel reminder from another user"}
        
        job = scheduler.get_job(job_id)
        if not job:
            logger.warning("Attempted to cancel non-existent reminder: {}", job_id)
            return {"success": False, "error": "Reminder not found"}
        
        scheduler.remove_job(job_id)
        logger.info("Cancelled reminder for user {} (job_id={})", user_id, job_id)
        return {"success": True}

    async def _list_reminders(self, user_id: int) -> Dict:
        """List all active reminders for the user."""
        from ..scheduler.scheduler_instance import scheduler
        from datetime import datetime
        from pytz import utc
        
        # Get all jobs for this user
        prefix = f"reminder_{user_id}_"
        user_jobs = [job for job in scheduler.get_jobs() if job.id.startswith(prefix)]
        
        reminders = []
        from datetime import timezone as _dt_timezone
        for job in user_jobs:
            # Extract reminder details from job
            if job.trigger and hasattr(job.trigger, 'run_date'):
                run_date = job.trigger.run_date
                # Convert to ISO format if it's a datetime
                if isinstance(run_date, datetime):
                    try:
                        run_date_iso = run_date.astimezone(_dt_timezone.utc).isoformat()
                    except Exception:
                        run_date_iso = run_date.isoformat()
                else:
                    run_date_iso = str(run_date)
            else:
                run_date_iso = "Unknown"
            
            # Extract message text from job args (format: [user_id, chat_id, message_text])
            message_text = job.args[2] if len(job.args) > 2 else "No message"
            
            reminders.append({
                "job_id": job.id,
                "message": message_text,
                "scheduled_for": run_date_iso,
            })
        
        logger.info("Listed {} active reminders for user {}", len(reminders), user_id)
        return {"success": True, "reminders": reminders, "count": len(reminders)}

    async def _create_plan(self, args: Dict, chat_id: int, user_id: int) -> Dict:
        """Create a plan (daily/weekly/monthly) and send it to user."""
        from datetime import datetime
        from aiogram import Bot
        from aiogram.client.default import DefaultBotProperties
        from sqlmodel import select
        from ..models.plan import Plan
        from ..config import settings

        plan_level = args["plan_level"]
        plan_content = args["plan_content"]

        # Validate plan level
        if plan_level not in ["daily", "weekly", "monthly"]:
            logger.warning("Invalid plan_level: {}", plan_level)
            return {"success": False, "error": f"Invalid plan level. Must be one of: daily, weekly, monthly"}

        try:
            # Create plan record in database
            expires_at = Plan.calculate_expiry(plan_level)
            plan = Plan(
                user_id=user_id,
                plan_level=plan_level,
                content=plan_content,
                expires_at=expires_at,
            )
            self.session.add(plan)
            await self.session.commit()

            # Send plan to user via Telegram
            bot = Bot(
                token=settings.TELEGRAM_BOT_TOKEN,
                default=DefaultBotProperties(parse_mode="HTML")
            )

            duration_text = {
                "daily": "на день",
                "weekly": "на неделю",
                "monthly": "на месяц",
            }.get(plan_level, "")

            message = f"📋 <b>Твой план {duration_text}:</b>\n\n{plan_content}"
            await bot.send_message(chat_id, message)
            await bot.session.close()

            logger.info("Created {} plan for user {} (plan_id={})", plan_level, user_id, plan.id)
            return {"success": True, "plan_id": plan.id}

        except Exception as e:
            logger.exception("Error creating plan for user {}: {}", user_id, e)
            await self.session.rollback()
            return {"success": False, "error": str(e)}

    async def _check_plan(self, user_id: int) -> Dict:
        """Check all active (non-expired) plans for the user."""
        from datetime import datetime, timezone
        from sqlmodel import select

        try:
            # Query non-expired plans
            result = await self.session.execute(
                select(
                    Plan.id,
                    Plan.plan_level,
                    Plan.content,
                    Plan.created_at,
                    Plan.expires_at,
                ).where(
                    Plan.user_id == user_id,
                    Plan.expires_at > datetime.now(timezone.utc),
                ).order_by(Plan.created_at.desc())
            )

            rows = result.all()
            plans = []

            for plan_id, plan_level, content, created_at, expires_at in rows:
                plans.append({
                    "plan_id": plan_id,
                    "plan_level": plan_level,
                    "content": content,
                    "created_at": created_at.isoformat() if isinstance(created_at, datetime) else str(created_at),
                    "expires_at": expires_at.isoformat() if isinstance(expires_at, datetime) else str(expires_at),
                })

            logger.info("Retrieved {} active plans for user {}", len(plans), user_id)
            return {"success": True, "plans": plans, "count": len(plans)}

        except Exception as e:
            logger.exception("Error checking plans for user {}: {}", user_id, e)
            return {"success": False, "error": str(e)}

    async def _edit_plan(self, args: Dict, chat_id: int, user_id: int) -> Dict:
        """Edit an existing plan and optionally extend its expiry."""
        from datetime import datetime, timezone
        from sqlmodel import select
        from aiogram import Bot
        from aiogram.client.default import DefaultBotProperties
        from ..config import settings

        plan_id = args.get("plan_id")
        plan_content = args.get("plan_content")
        extend_expiry = args.get("extend_expiry", False)

        try:
            # Fetch the plan
            result = await self.session.execute(
                select(Plan).where(
                    Plan.id == plan_id,
                    Plan.user_id == user_id,
                )
            )
            plan = result.scalar_one_or_none()

            if not plan:
                logger.warning("User {} attempted to edit non-existent plan: {}", user_id, plan_id)
                return {"success": False, "error": "Plan not found"}

            # Check if plan has expired
            if plan.is_expired():
                logger.warning("User {} attempted to edit expired plan: {}", user_id, plan_id)
                return {"success": False, "error": "Plan has expired"}

            # Update plan content
            plan.content = plan_content

            # Extend expiry if requested
            if extend_expiry:
                plan.expires_at = Plan.calculate_expiry(plan.plan_level)
                logger.info("Extended expiry for plan {} to {}", plan_id, plan.expires_at)

            self.session.add(plan)
            await self.session.commit()

            # Send updated plan to user via Telegram
            bot = Bot(
                token=settings.TELEGRAM_BOT_TOKEN,
                default=DefaultBotProperties(parse_mode="HTML")
            )

            duration_text = {
                "daily": "на день",
                "weekly": "на неделю",
                "monthly": "на месяц",
            }.get(plan.plan_level, "")

            message = f"✏️ <b>Обновленный план {duration_text}:</b>\n\n{plan_content}"
            await bot.send_message(chat_id, message)
            await bot.session.close()

            logger.info("Edited plan {} for user {}", plan_id, user_id)
            return {
                "success": True,
                "plan_id": plan.id,
                "expires_at": plan.expires_at.isoformat() if isinstance(plan.expires_at, datetime) else str(plan.expires_at),
            }

        except Exception as e:
            logger.exception("Error editing plan for user {}: {}", user_id, e)
            await self.session.rollback()
            return {"success": False, "error": str(e)}

