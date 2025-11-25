from __future__ import annotations
from typing import Any, Dict
from datetime import datetime, timezone
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from ..mcp_client.client import MCPClient
from apscheduler.triggers.date import DateTrigger

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
            if tool_name == "send_telegram_message_and_pin":
                return await self._send_telegram_message_and_pin(args, chat_id)
            elif tool_name == "schedule_reminder":
                return await self._schedule_reminder(args, chat_id, user_id)
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
        from datetime import datetime, timezone
        
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
        from datetime import datetime
        from pytz import utc
        from ..scheduler.scheduler_instance import scheduler

        reminder_dt = datetime.fromisoformat(args["reminder_datetime_iso"])
        # Assume reminder_dt is already in UTC or naive (treated as UTC)
        if reminder_dt.tzinfo is None:
            reminder_dt = reminder_dt.replace(tzinfo=utc)

        job_id = f"reminder_{user_id}_{int(reminder_dt.timestamp())}"

        # Avoid duplicates for same user/time
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)

        trigger = DateTrigger(run_date=reminder_dt, timezone=utc)

        scheduler.add_job(
            func="app.scheduler.jobs:send_one_off_reminder_job",
            trigger=trigger,
            id=job_id,
            args=[user_id, chat_id, args["message_text"]],
            replace_existing=True,
        )

        logger.info("Scheduled one-off reminder for user {} at {} (job_id={})", user_id, reminder_dt, job_id)
        return {"success": True, "job_id": job_id}

    async def _send_telegram_message_and_pin(self, args: Dict, chat_id: int) -> Dict:
        """Pin a message."""
        await self.mcp.send_telegram_message_and_pin(
            chat_id=chat_id,
            message_text=args["message_text"],
            disable_notification=args.get("disable_notification", True)
        )
        return {"success": True}