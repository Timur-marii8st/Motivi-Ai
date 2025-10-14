from __future__ import annotations
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger
from aiogram import Bot

from ..models.users import User
from ..config import settings
from ..services.memory_orchestrator import MemoryOrchestrator
from ..services.episodic_memory_service import EpisodicMemoryService
from ..embeddings.gemini_embedding_client import GeminiEmbeddings
from ..llm.conversation_service import ConversationService
from ..mcp_client.client import MCPClient
from ..services.tool_executor import ToolExecutor

class ProactiveFlows:
    """
    Orchestrates proactive interactions: morning, evening, weekly, monthly.
    """
    def __init__(self, session: AsyncSession):
        self.session = session
        self.bot = Bot(token=settings.TELEGRAM_BOT_TOKEN, parse_mode="HTML")
        
        # Services
        self.gemini_embeddings = GeminiEmbeddings()
        self.episodic_service = EpisodicMemoryService(self.gemini_embeddings)
        self.memory_orchestrator = MemoryOrchestrator(self.episodic_service)
        self.conversation_service = ConversationService()
        
        self.mcp_client = MCPClient(settings.MCP_BASE_URL, settings.MCP_SECRET_TOKEN)
        self.tool_executor = ToolExecutor(session, self.mcp_client)

    async def morning_checkin(self, user: User):
        """
        Morning check-in: greet, suggest top tasks, motivate.
        """
        greeting = f"Good morning, {user.name}! ☀️"
        
        prompt = (
            "It's morning. Help me plan my day. "
            "Check my recent episodes, suggest 3 top-priority tasks, and motivate me."
        )
        
        memory_pack = await self.memory_orchestrator.assemble(self.session, user, prompt, top_k=5)
        
        response, _ = await self.conversation_service.respond_with_tools(
            prompt, memory_pack, user.tg_chat_id, self.tool_executor, self.session
        )
        
        message = f"{greeting}\n\n{response}"
        await self.bot.send_message(user.tg_chat_id, message)
        
        logger.info("Morning check-in sent to user {}", user.id)

    async def evening_wrapup(self, user: User):
        """
        Evening wrap-up: reflect, log wins, encourage.
        """
        greeting = f"Good evening, {user.name}! 🌙"
        
        prompt = (
            "It's evening. Let's wrap up the day. "
            "Ask me what went well, what I completed, and encourage me for tomorrow."
        )
        
        memory_pack = await self.memory_orchestrator.assemble(self.session, user, prompt, top_k=5)
        
        response, _ = await self.conversation_service.respond_with_tools(
            prompt, memory_pack, user.tg_chat_id, self.tool_executor, self.session
        )
        
        message = f"{greeting}\n\n{response}"
        await self.bot.send_message(user.tg_chat_id, message)
        
        logger.info("Evening wrap-up sent to user {}", user.id)

    async def weekly_plan(self, user: User):
        """
        Generate weekly plan, create docx, send, and pin.
        """
        now = datetime.now()
        week_start = now.strftime("%b %d")
        week_end = (now + timedelta(days=7)).strftime("%b %d")
        
        prompt = (
            f"Generate a detailed weekly plan for {week_start} to {week_end}. "
            "Use my goals, recent episodes, and habits. "
            "Create a structured document with sections: Goals, Daily Breakdown, Habits to Focus On. "
            "Use the create_and_send_plan_document tool."
        )
        
        memory_pack = await self.memory_orchestrator.assemble(self.session, user, prompt, top_k=10)
        
        response, _ = await self.conversation_service.respond_with_tools(
            prompt, memory_pack, user.tg_chat_id, self.tool_executor, self.session
        )
        
        # Tool should have handled document creation; send confirmation
        await self.bot.send_message(user.tg_chat_id, f"📅 Your weekly plan is ready!\n\n{response}")
        
        logger.info("Weekly plan generated for user {}", user.id)

    async def monthly_plan(self, user: User):
        """
        Generate monthly plan.
        """
        now = datetime.now()
        month = now.strftime("%B %Y")
        
        prompt = (
            f"Generate a comprehensive monthly plan for {month}. "
            "Review my long-term goals, past achievements, and set milestones. "
            "Structure: Overview, Weekly Themes, Key Milestones, Habits. "
            "Use the create_and_send_plan_document tool."
        )
        
        memory_pack = await self.memory_orchestrator.assemble(self.session, user, prompt, top_k=15)
        
        response, _ = await self.conversation_service.respond_with_tools(
            prompt, memory_pack, user.tg_chat_id, self.tool_executor, self.session
        )
        
        await self.bot.send_message(user.tg_chat_id, f"📆 Your monthly plan is ready!\n\n{response}")
        
        logger.info("Monthly plan generated for user {}", user.id)