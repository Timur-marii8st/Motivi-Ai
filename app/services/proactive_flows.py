from __future__ import annotations
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties

from ..models.users import User
from ..config import settings
from ..services.memory_orchestrator import MemoryOrchestrator
from ..services.episodic_memory_service import EpisodicMemoryService
from ..services.core_memory_service import CoreMemoryService
from ..services.working_memory_service import WorkingMemoryService
from ..embeddings.gemini_embedding_client import GeminiEmbeddings
from ..llm.conversation_service import ConversationService
from ..services.tool_executor import ToolExecutor
from ..services.conversation_history_service import ConversationHistoryService
from ..services.extractor_service import ExtractorService

class ProactiveFlows:
    """
    Orchestrates proactive interactions: morning, evening, weekly, monthly.
    """
    def __init__(self, session: AsyncSession):
        self.session = session

        self.bot = Bot(
            token=settings.TELEGRAM_BOT_TOKEN, 
            default=DefaultBotProperties(parse_mode="HTML")
        )
        
        # Services
        self.gemini_embeddings = GeminiEmbeddings()
        self.episodic_service = EpisodicMemoryService(self.gemini_embeddings)
        self.core_service = CoreMemoryService(self.gemini_embeddings)
        self.working_service = WorkingMemoryService(self.gemini_embeddings)
        self.memory_orchestrator = MemoryOrchestrator(self.episodic_service, self.core_service, self.working_service)
        self.conversation_service = ConversationService()
        self.extractor_service = ExtractorService()
        
        self.tool_executor = ToolExecutor(session)

    async def morning_checkin(self, user: User):
        """
        Morning check-in: greet, suggest top tasks, motivate.
        """
        try:
            greeting = f"Good morning, {user.name}! ☀️"
            
            prompt = (
                "It's morning. Help me plan my day. "
                "Check my recent episodes, suggest 3 top-priority tasks, and motivate me."
            )
            
            # Load conversation history
            history = await ConversationHistoryService.get_history(user.tg_chat_id)
            
            memory_pack = await self.memory_orchestrator.assemble(self.session, user, prompt, top_k=5)
            
            response, updated_history = await self.conversation_service.respond_with_tools(
                prompt, memory_pack, user.tg_chat_id, self.tool_executor, self.session, conversation_history=history
            )
            
            # Save updated history
            await ConversationHistoryService.save_history(user.tg_chat_id, updated_history)
            
            message = f"{greeting}\n\n{response}"
            await self.bot.send_message(user.tg_chat_id, message)
            
            # Extract important info from the conversation
            try:
                info_text = f"User message: {prompt}\nAI Assistant message: {response}"
                await self.extractor_service.find_write_important_info(user.id, self.session, info_text)
                logger.info("Extracted important info from morning check-in for user {}", user.id)
            except Exception as e:
                logger.exception("Failed to extract info from morning check-in for user {}: {}", user.id, e)
            
            logger.info("Morning check-in sent to user {}", user.id)
        except Exception as e:
            logger.exception("Error sending morning check-in to user {}: {}", user.id, e)
            raise

    async def evening_wrapup(self, user: User):
        """
        Evening wrap-up: reflect, log wins, encourage.
        """
        try:
            greeting = f"Good evening, {user.name}! 🌙"
            
            prompt = (
                "It's evening. Let's wrap up the day. "
                "Ask me what went well, what I completed, and encourage me for tomorrow."
            )
            
            # Load conversation history
            history = await ConversationHistoryService.get_history(user.tg_chat_id)
            
            memory_pack = await self.memory_orchestrator.assemble(self.session, user, prompt, top_k=5)
            
            response, updated_history = await self.conversation_service.respond_with_tools(
                prompt, memory_pack, user.tg_chat_id, self.tool_executor, self.session, conversation_history=history
            )
            
            # Save updated history
            await ConversationHistoryService.save_history(user.tg_chat_id, updated_history)
            
            message = f"{greeting}\n\n{response}"
            await self.bot.send_message(user.tg_chat_id, message)
            
            # Extract important info from the conversation
            try:
                info_text = f"User message: {prompt}\nAI Assistant message: {response}"
                await self.extractor_service.find_write_important_info(user.id, self.session, info_text)
                logger.info("Extracted important info from evening wrap-up for user {}", user.id)
            except Exception as e:
                logger.exception("Failed to extract info from evening wrap-up for user {}: {}", user.id, e)
            
            logger.info("Evening wrap-up sent to user {}", user.id)
        except Exception as e:
            logger.exception("Error sending evening wrap-up to user {}: {}", user.id, e)
            raise

    async def weekly_plan(self, user: User):
        """
        Generate weekly plan, send and pin.
        """
        try:
            now = datetime.now(timezone.utc)
            week_start = now.strftime("%b %d")
            week_end = (now + timedelta(days=7)).strftime("%b %d")
            
            prompt = (
                f"Generate a detailed weekly plan for {week_start} to {week_end}. "
                "Use my goals, recent episodes, and habits. "
                "Create a structured document with sections: Goals, Daily Breakdown, Habits to Focus On. "
            )
            
            # Load conversation history
            history = await ConversationHistoryService.get_history(user.tg_chat_id)
            
            memory_pack = await self.memory_orchestrator.assemble(self.session, user, prompt, top_k=10)
            
            response, updated_history = await self.conversation_service.respond_with_tools(
                prompt, memory_pack, user.tg_chat_id, self.tool_executor, self.session, conversation_history=history
            )
            
            # Save updated history
            await ConversationHistoryService.save_history(user.tg_chat_id, updated_history)
            
            # Tool should have handled document creation; send confirmation
            await self.bot.send_message(user.tg_chat_id, f"📅 Your weekly plan is ready!\n\n{response}")
            
            # Extract important info from the conversation
            try:
                info_text = f"User message: {prompt}\nAI Assistant message: {response}"
                await self.extractor_service.find_write_important_info(user.id, self.session, info_text)
                logger.info("Extracted important info from weekly plan for user {}", user.id)
            except Exception as e:
                logger.exception("Failed to extract info from weekly plan for user {}: {}", user.id, e)
            
            logger.info("Weekly plan generated for user {}", user.id)
        except Exception as e:
            logger.exception("Error generating weekly plan for user {}: {}", user.id, e)
            raise

    async def monthly_plan(self, user: User):
        """
        Generate monthly plan.
        """
        try:
            now = datetime.now(timezone.utc)
            month = now.strftime("%B %Y")
            
            prompt = (
                f"Generate a comprehensive monthly plan for {month}. "
                "Review my long-term goals, past achievements, and set milestones. "
                "Structure: Overview, Weekly Themes, Key Milestones, Habits. "
            )
            
            # Load conversation history
            history = await ConversationHistoryService.get_history(user.tg_chat_id)
            
            memory_pack = await self.memory_orchestrator.assemble(self.session, user, prompt, top_k=15)
            
            response, updated_history = await self.conversation_service.respond_with_tools(
                prompt, memory_pack, user.tg_chat_id, self.tool_executor, self.session, conversation_history=history
            )
            
            # Save updated history
            await ConversationHistoryService.save_history(user.tg_chat_id, updated_history)
            
            await self.bot.send_message(user.tg_chat_id, f"📆 Your monthly plan is ready!\n\n{response}")
            
            # Extract important info from the conversation
            try:
                info_text = f"User message: {prompt}\nAI Assistant message: {response}"
                await self.extractor_service.find_write_important_info(user.id, self.session, info_text)
                logger.info("Extracted important info from monthly plan for user {}", user.id)
            except Exception as e:
                logger.exception("Failed to extract info from monthly plan for user {}: {}", user.id, e)
            
            logger.info("Monthly plan generated for user {}", user.id)
        except Exception as e:
            logger.exception("Error generating monthly plan for user {}: {}", user.id, e)
            raise