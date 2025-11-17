from __future__ import annotations
from typing import Any, Dict
from datetime import datetime, timezone
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from ..mcp_client.client import MCPClient
from ..models.task import Task

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
            if tool_name == "create_task":
                return await self._create_task(args, user_id)
            elif tool_name == "send_telegram_message_and_pin":
                return await self._send_telegram_message_and_pin(args, chat_id)
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

    async def _create_task(self, args: Dict, user_id: int) -> Dict:
        """Create a task in database."""
        due_dt = None
        if args.get("due_date_iso"):
            try:
                due_dt = datetime.fromisoformat(args["due_date_iso"])
            except Exception:
                pass
        
        task = Task(
            user_id=user_id,
            title=args["title"],
            description=args.get("description"),
            due_dt=due_dt,
            status="todo",
            created_from_plan=True,
        )
        self.session.add(task)
        await self.session.flush()
        
        logger.info("Created task {} for user {}", task.id, user_id)
        return {"success": True, "task_id": task.id}

    async def _send_telegram_message_and_pin(self, args: Dict, chat_id: int) -> Dict:
        """Pin a message."""
        await self.mcp.send_telegram_message_and_pin(
            chat_id=chat_id,
            message_text=args["message_text"],
            disable_notification=args.get("disable_notification", True)
        )
        return {"success": True}