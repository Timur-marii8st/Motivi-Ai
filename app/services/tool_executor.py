from __future__ import annotations
from typing import Any, Dict, TYPE_CHECKING
from datetime import datetime, timezone as _tz

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.plan import Plan

if TYPE_CHECKING:
    from aiogram import Bot

class ToolExecutor:
    def __init__(self, session: AsyncSession, bot: Bot | None = None):
        self.session = session
        self.bot = bot

    def _require_bot(self) -> Bot:
        if self.bot is None:
            raise RuntimeError("ToolExecutor requires bot instance for Telegram send operations")
        return self.bot

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
            elif tool_name == "execute_code":
                return await self._execute_code(args, chat_id, user_id)
            elif tool_name == "load_skill":
                return await self._load_skill(args)
            elif tool_name == "web_search":
                return await self._web_search(args, user_id)
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
        from ..models.users import User
        from zoneinfo import ZoneInfo

        # Get reminder datetime (naive local time from LLM)
        iso_str = args["reminder_datetime_iso"]
        if iso_str.endswith("Z"):
            iso_str = iso_str[:-1] + "+00:00"
        
        reminder_dt = datetime.fromisoformat(iso_str)
        
        # Timezone priority:
        # 1) Explicit tool arg (if provided)
        # 2) User profile timezone
        # 3) UTC fallback
        try:
            user = await self.session.get(User, user_id)
            explicit_tz = args.get("timezone")
            if explicit_tz:
                tzname = str(explicit_tz)
            else:
                tzname = user.user_timezone if user and user.user_timezone else "UTC"
        except Exception as e:
            logger.error("Failed to get user timezone for user {}: {}", user_id, e)
            tzname = "UTC"
        
        # Convert local time to UTC
        now_utc = datetime.now(_utc)
        
        if reminder_dt.tzinfo is None:
            # Naive datetime - interpret as local time in user's timezone
            try:
                local_tz = ZoneInfo(tzname)
                # Localize the naive datetime to user's timezone
                reminder_dt_local = reminder_dt.replace(tzinfo=local_tz)
                # Convert to UTC for scheduling
                reminder_dt_utc = reminder_dt_local.astimezone(_utc)
            except Exception as e:
                logger.error("Failed to convert timezone {} for user {}: {}", tzname, user_id, e)
                return {"success": False, "error": f"Invalid timezone: {tzname}"}
        else:
            # Already timezone-aware, convert to UTC
            reminder_dt_utc = reminder_dt.astimezone(_utc)
            reminder_dt_local = reminder_dt
        
        # Do not allow scheduling reminders in the past
        if reminder_dt_utc <= now_utc:
            logger.warning("Attempted to schedule reminder in the past: {} UTC (now={})", reminder_dt_utc, now_utc)
            return {"success": False, "error": "Cannot schedule a reminder in the past. Please provide a future time."}
        
        # Generate unique job_id
        unique_id = str(uuid.uuid4())[:8]
        job_id = f"reminder_{user_id}_{unique_id}"
        
        # Check if job already exists and remove it
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
        
        from apscheduler.triggers.date import DateTrigger
        # Ensure the scheduler is running
        try:
            if not scheduler.running:
                start_scheduler()
        except Exception:
            logger.debug("Could not ensure scheduler was running when scheduling reminder")
        
        trigger = DateTrigger(run_date=reminder_dt_utc, timezone=_utc)
        
        scheduler.add_job(
            func="app.scheduler.jobs:send_one_off_reminder_job",
            trigger=trigger,
            id=job_id,
            args=[user_id, chat_id, args["message_text"]],
            replace_existing=True,
        )
        
        # Build human-friendly time info
        scheduled_utc_iso = reminder_dt_utc.isoformat()
        scheduled_local_iso = reminder_dt_local.isoformat() if 'reminder_dt_local' in locals() else scheduled_utc_iso
        
        logger.info("Scheduled reminder for user {} at {} UTC ({} local in {})", 
                   user_id, reminder_dt_utc, reminder_dt_local if 'reminder_dt_local' in locals() else 'N/A', tzname)
        
        return {
            "success": True,
            "job_id": job_id,
            "scheduled_for_utc": scheduled_utc_iso,
            "scheduled_for_local": scheduled_local_iso,
            "timezone": tzname,
        }

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
            # Fetch user's configured timezone (falls back to UTC)
            user_tz = None
            try:
                from ..models.users import User
                user_obj = await self.session.get(User, user_id)
                user_tz = getattr(user_obj, "user_timezone", None)
            except Exception:
                user_tz = None

            scheduled_for_local = None
            if isinstance(run_date, datetime):
                try:
                    if user_tz:
                        from zoneinfo import ZoneInfo
                        scheduled_for_local = run_date.astimezone(ZoneInfo(user_tz)).isoformat()
                    else:
                        scheduled_for_local = run_date_iso
                except Exception:
                    scheduled_for_local = run_date_iso

            reminders.append({
                "job_id": job.id,
                "message": message_text,
                "scheduled_for": run_date_iso,
                "scheduled_for_local": scheduled_for_local,
                "timezone": user_tz or "UTC",
            })
        
        logger.info("Listed {} active reminders for user {}", len(reminders), user_id)
        return {"success": True, "reminders": reminders, "count": len(reminders)}

    async def _create_plan(self, args: Dict, chat_id: int, user_id: int) -> Dict:
        """Create a plan (daily/weekly/monthly) and send it to user."""
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
            # Don't commit here - let middleware handle transaction
            # This ensures atomicity: if Telegram send fails, plan won't be saved
            await self.session.flush()  # Flush to get plan.id without committing

            # Send plan to user via Telegram
            bot = self._require_bot()

            duration_text = {
                "daily": "на день",
                "weekly": "на неделю",
                "monthly": "на месяц",
            }.get(plan_level, "")

            message = f"📋 <b>Твой план {duration_text}:</b>\n\n{plan_content}"
            await bot.send_message(chat_id, message)

            logger.info("Created {} plan for user {} (plan_id={})", plan_level, user_id, plan.id)
            return {"success": True, "plan_id": plan.id}

        except Exception as e:
            logger.exception("Error creating plan for user {}: {}", user_id, e)
            # Don't rollback - let the caller/middleware handle transaction fate
            # The session is shared with the handler
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
        from datetime import datetime
        from sqlmodel import select

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
            # Don't commit here - let middleware handle transaction
            await self.session.flush()  # Flush to persist changes without committing

            # Send updated plan to user via Telegram
            bot = self._require_bot()

            duration_text = {
                "daily": "на день",
                "weekly": "на неделю",
                "monthly": "на месяц",
            }.get(plan.plan_level, "")

            message = f"✏️ <b>Обновленный план {duration_text}:</b>\n\n{plan_content}"
            await bot.send_message(chat_id, message)

            logger.info("Edited plan {} for user {}", plan_id, user_id)
            return {
                "success": True,
                "plan_id": plan.id,
                "expires_at": plan.expires_at.isoformat() if isinstance(plan.expires_at, datetime) else str(plan.expires_at),
            }

        except Exception as e:
            logger.exception("Error editing plan for user {}: {}", user_id, e)
            # Don't rollback - let the caller/middleware handle transaction fate
            # The session is shared with the handler
            return {"success": False, "error": str(e)}

    async def _execute_code(self, args: dict, chat_id: int, user_id: int) -> dict:
        """Execute code in a sandboxed Docker container with subscription gate and rate limiting.

        For Python executions, any files saved to /output/ inside the container are
        collected and sent directly to the user via Telegram (photos for images, documents
        for everything else). The LLM receives a summary of what was sent.
        """
        from ..services.code_executor_service import code_executor, SUPPORTED_LANGUAGES
        from ..services.subscription_service import SubscriptionService
        from ..services.conversation_history_service import ConversationHistoryService
        from ..models.users import User
        from ..config import settings

        _IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp"})

        language = args.get("language", "").lower().strip()
        code = args.get("code", "").strip()

        if not language:
            return {"success": False, "error": "language is required"}
        if not code:
            return {"success": False, "error": "code is required"}
        if language not in SUPPORTED_LANGUAGES:
            return {
                "success": False,
                "error": f"Unsupported language '{language}'. Use one of: {', '.join(SUPPORTED_LANGUAGES)}",
            }

        # Subscription gate
        user = await self.session.get(User, user_id)
        if not user:
            return {"success": False, "error": "User not found"}

        status = await SubscriptionService.get_user_status(user)
        if status == "expired":
            return {
                "success": False,
                "error": "Code execution requires an active subscription. Use /subscribe to upgrade.",
            }

        # Rate limiting (skip for admins)
        if status != "admin":
            limit = (
                settings.CODE_EXEC_DAILY_PREMIUM
                if status == "premium"
                else settings.CODE_EXEC_DAILY_TRIAL
            )
            redis = ConversationHistoryService._get_redis_client()
            today_str = datetime.now(_tz.utc).strftime("%Y-%m-%d")
            counter_key = f"code_exec:{user_id}:{today_str}"
            async with redis.pipeline(transaction=True) as pipe:
                pipe.incr(counter_key)
                pipe.execute_command("EXPIRE", counter_key, 86400 + 3600, "NX")
                pipe_result = await pipe.execute()
            current_count = int(pipe_result[0])
            if current_count > limit:
                if settings.is_feature_enabled("F010_CONTEXTUAL_UPGRADE"):
                    return {
                        "success": False,
                        "error": (
                            f"You've used all {limit} code executions today. "
                            f"I was ready to help you with that — unlock "
                            f"{settings.CODE_EXEC_DAILY_PREMIUM} daily executions "
                            f"with Premium! Use /subscribe to upgrade."
                        ),
                    }
                return {
                    "success": False,
                    "error": f"Daily code execution limit reached ({limit}/day). Try again tomorrow.",
                }

        result = await code_executor.run(language=language, code=code)
        result_dict = result.to_dict()

        # Send any output files directly to the user via Telegram
        if result.output_files:
            from aiogram.types import BufferedInputFile
            bot = self._require_bot()
            sent_files: list[str] = []
            failed_files: list[str] = []
            for fname, fdata in result.output_files:
                from pathlib import Path
                ext = Path(fname).suffix.lower()
                try:
                    input_file = BufferedInputFile(fdata, filename=fname)
                    if ext in _IMAGE_EXTENSIONS:
                        await bot.send_photo(chat_id, input_file)
                    else:
                        await bot.send_document(chat_id, input_file)
                    sent_files.append(fname)
                    logger.info("Sent output file {} to chat {}", fname, chat_id)
                except Exception as e:
                    logger.warning("Failed to send output file {} to chat {}: {}", fname, chat_id, e)
                    failed_files.append(fname)

            result_dict["output_files_sent"] = sent_files
            if failed_files:
                result_dict["output_files_failed"] = failed_files

        return result_dict

    async def _web_search(self, args: dict, user_id: int) -> dict:
        """
        Execute a web search via Tavily with subscription gate and rate limiting.
        Returns structured results for the LLM to summarise.
        """
        from ..services.search_service import SearchService
        from ..services.subscription_service import SubscriptionService
        from ..models.users import User

        query = (args.get("query") or "").strip()
        if not query:
            return {"success": False, "error": "query is required"}

        num_results = int(args.get("num_results") or 5)
        search_type = args.get("search_type") or "general"
        if search_type not in ("general", "news"):
            search_type = "general"

        # Subscription gate
        user = await self.session.get(User, user_id)
        if not user:
            return {"success": False, "error": "User not found"}

        status = await SubscriptionService.get_user_status(user)
        if status == "expired":
            return {
                "success": False,
                "error": (
                    "Web search requires an active subscription. "
                    "Use /subscribe to upgrade."
                ),
            }

        # Rate limiting (admins bypass)
        allowed, count, limit = await SearchService.check_rate_limit(
            user_id=user_id,
            is_premium=(status == "premium"),
            is_admin=(status == "admin"),
        )
        if not allowed:
            if settings.is_feature_enabled("F010_CONTEXTUAL_UPGRADE"):
                return {
                    "success": False,
                    "error": (
                        f"You've hit your daily search limit of {limit}. "
                        f"Unlock {settings.SEARCH_DAILY_PREMIUM} daily searches "
                        f"with Premium! Use /subscribe to upgrade."
                    ),
                }
            return {
                "success": False,
                "error": (
                    f"Daily search limit reached ({limit}/day). "
                    "Try again tomorrow."
                ),
            }

        results = await SearchService.search(
            query=query,
            num_results=num_results,
            search_type=search_type,
        )

        if not results:
            return {
                "success": True,
                "query": query,
                "results": [],
                "note": (
                    "No results found. The search API may be unavailable "
                    "or the query returned nothing."
                ),
            }

        formatted = SearchService.format_results_for_llm(results)
        return {
            "success": True,
            "query": query,
            "search_type": search_type,
            "results": results,
            "formatted": formatted,
            "count": len(results),
        }

    async def _load_skill(self, args: dict) -> dict:
        """Load and return the full instructions for a named Agent Skill."""
        from ..services.skills_service import SkillsService

        name = args.get("name", "").strip()
        if not name:
            return {"success": False, "error": "name is required"}

        content = SkillsService.get_skill_content(name)
        if content is None:
            available = SkillsService.get_available_names()
            return {
                "success": False,
                "error": (
                    f"Skill '{name}' not found. "
                    f"Available skills: {', '.join(available) if available else 'none installed'}"
                ),
            }

        return {"success": True, "skill_name": name, "instructions": content}

