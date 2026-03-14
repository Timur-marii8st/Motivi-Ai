from __future__ import annotations
import asyncio
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger
from aiogram import Bot

from ..models.users import User
from ..bot.bot_provider import get_bot_instance
from ..services.memory_orchestrator import MemoryOrchestrator
from ..services.episodic_memory_service import EpisodicMemoryService
from ..services.core_memory_service import CoreMemoryService
from ..services.working_memory_service import WorkingMemoryService
from ..embeddings.gemini_embedding_client import GeminiEmbeddings
from ..llm.conversation_service import ConversationService
from ..services.tool_executor import ToolExecutor
from ..services.conversation_history_service import ConversationHistoryService
from ..services.extractor_service import ExtractorService

# Singleton embeddings shared across all ProactiveFlows instances
_shared_embeddings = GeminiEmbeddings()


class ProactiveFlows:
    """
    Orchestrates proactive interactions: morning, evening, weekly, monthly.
    """
    def __init__(self, session: AsyncSession, bot: Bot | None = None):
        self.session = session
        self.bot = bot or get_bot_instance()
        # Reuse shared embeddings client instead of creating one per instance
        self.episodic_service = EpisodicMemoryService(_shared_embeddings)
        self.core_service = CoreMemoryService(_shared_embeddings)
        self.working_service = WorkingMemoryService(_shared_embeddings)
        self.memory_orchestrator = MemoryOrchestrator(self.episodic_service, self.core_service, self.working_service)
        self.conversation_service = ConversationService()
        self.extractor_service = ExtractorService()
        self.tool_executor = ToolExecutor(session, bot=self.bot)

    async def _run_flow(self, user: User, prompt: str, greeting: str, top_k: int = 5) -> None:
        """
        Shared helper for all proactive flows. Handles memory assembly,
        LLM call, message delivery, history persistence, and fact extraction.
        """
        # Load user's language preference for correct persona selection
        language = "ru"
        try:
            from ..services.settings_service import SettingsService
            user_settings = await SettingsService.get_or_create(self.session, user.id)
            language = (user_settings.summary_preferences_json or {}).get("language", "ru")
        except Exception:
            pass  # Fall back to Russian on any error

        history = await ConversationHistoryService.get_history(user.tg_chat_id)
        memory_pack = await self.memory_orchestrator.assemble(self.session, user, prompt, top_k=top_k)
        response, updated_history = await self.conversation_service.respond_with_tools(
            prompt, memory_pack, user.tg_chat_id, self.tool_executor, self.session,
            conversation_history=history, language=language,
        )
        # Build final message: skip leading newlines if greeting is empty
        message_text = f"{greeting}\n\n{response}" if greeting else response
        # Persist history and send message concurrently
        await asyncio.gather(
            ConversationHistoryService.save_history(user.tg_chat_id, updated_history),
            self.bot.send_message(user.tg_chat_id, message_text),
        )
        # Extract and store important info — non-fatal if it fails
        try:
            info_text = f"User message: {prompt}\nAI Assistant message: {response}"
            await self.extractor_service.find_write_important_info(user.id, self.session, info_text)
        except Exception as e:
            logger.exception("Failed to extract info from proactive flow for user {}: {}", user.id, e)

    async def morning_checkin(self, user: User):
        """Morning check-in: greet, suggest top tasks, motivate.

        Enhanced with adaptive tone (F014) and morning challenges (F015).
        """
        logger.info("Morning check-in for user {}", user.id)
        try:
            import random

            prompt = (
                "It's morning. Help me plan my day. "
                "Check my recent episodes, suggest 3 top-priority tasks, and motivate me."
            )

            # ── Adaptive Morning Tone (F014) ──
            if settings.is_feature_enabled("F014_ADAPTIVE_TONE"):
                try:
                    from ..services.mood_service import get_morning_mood_context
                    mood_ctx = await get_morning_mood_context(user.id)
                    if mood_ctx:
                        prompt = f"{mood_ctx}\n\n{prompt}"
                except Exception as e:
                    logger.warning("Mood context failed for user {}: {}", user.id, e)

            # ── Morning Challenge Cards (F015) — ~40% chance ──
            if settings.is_feature_enabled("F015_MORNING_CHALLENGES") and random.random() < 0.4:
                prompt += (
                    "\n\nAlso include a small, achievable challenge for today "
                    "based on my goals and habits. Frame it as "
                    "'🎯 Today\\'s challenge: [specific action]'. "
                    "Make it relevant to my current context."
                )

            # ── Streak info in greeting ──
            greeting = f"Good morning, {user.name}! \u2600\ufe0f"
            if settings.is_feature_enabled("F006_STREAKS"):
                from ..services.streak_service import StreakService
                streak_display = StreakService.get_streak_display(user)
                if streak_display:
                    greeting += f"\n{streak_display}"

            await self._run_flow(
                user=user,
                prompt=prompt,
                greeting=greeting,
                top_k=5,
            )
            logger.info("Morning check-in sent to user {}", user.id)
        except Exception as e:
            logger.exception("Error sending morning check-in to user {}: {}", user.id, e)
            raise

    async def evening_wrapup(self, user: User):
        """Evening wrap-up: reflect, log wins, encourage.

        Also extracts mood signal for adaptive morning tone (F014).
        """
        logger.info("Evening wrap-up for user {}", user.id)
        try:
            await self._run_flow(
                user=user,
                prompt=(
                    "It's evening. Let's wrap up the day. "
                    "Ask me what went well, what I completed, and encourage me for tomorrow."
                ),
                greeting=f"Good evening, {user.name}! \U0001f319",
                top_k=5,
            )
            logger.info("Evening wrap-up sent to user {}", user.id)

            # ── Extract mood for adaptive morning tone (F014) ──
            if settings.is_feature_enabled("F014_ADAPTIVE_TONE"):
                try:
                    from ..services.mood_service import extract_mood, store_mood_signal
                    history = await ConversationHistoryService.get_history(user.tg_chat_id)
                    if history:
                        recent_text = "\n".join(
                            m.get("content", "")
                            for m in history[-10:]
                            if m.get("content")
                        )
                        mood = await extract_mood(recent_text)
                        await store_mood_signal(user.id, mood)
                        logger.info("Stored mood '{}' for user {}", mood, user.id)
                except Exception as e:
                    logger.warning("Mood extraction failed for user {}: {}", user.id, e)
        except Exception as e:
            logger.exception("Error sending evening wrap-up to user {}: {}", user.id, e)
            raise

    async def weekly_plan(self, user: User):
        """Generate weekly plan."""
        logger.info("Weekly plan for user {}", user.id)
        try:
            now = datetime.now(timezone.utc)
            week_start = now.strftime("%b %d")
            week_end = (now + timedelta(days=7)).strftime("%b %d")
            await self._run_flow(
                user=user,
                prompt=(
                    f"Generate a detailed weekly plan for {week_start} to {week_end}. "
                    "Use my goals, recent episodes, and habits. "
                    "Create a structured document with sections: Goals, Daily Breakdown, Habits to Focus On."
                ),
                greeting=f"\U0001f4c5 Your weekly plan is ready!",
                top_k=10,
            )
            logger.info("Weekly plan generated for user {}", user.id)
        except Exception as e:
            logger.exception("Error generating weekly plan for user {}: {}", user.id, e)
            raise

    async def monthly_plan(self, user: User):
        """Generate monthly plan."""
        logger.info("Monthly plan for user {}", user.id)
        try:
            now = datetime.now(timezone.utc)
            month = now.strftime("%B %Y")
            await self._run_flow(
                user=user,
                prompt=(
                    f"Generate a comprehensive monthly plan for {month}. "
                    "Review my long-term goals, past achievements, and set milestones. "
                    "Structure: Overview, Weekly Themes, Key Milestones, Habits."
                ),
                greeting=f"\U0001f4c6 Your monthly plan is ready!",
                top_k=15,
            )
            logger.info("Monthly plan generated for user {}", user.id)
        except Exception as e:
            logger.exception("Error generating monthly plan for user {}: {}", user.id, e)
            raise

    async def news_digest(self, user: User):
        """
        Deliver a personalised news digest.

        Fetches fresh news articles matched to the user's interests (from core
        memory) via SearchService/NewsDigestService, then passes them to the
        LLM through _run_flow so it can curate, comment, and summarise them
        using the full user memory context.
        """
        logger.info("News digest for user {}", user.id)
        try:
            from .news_digest_service import NewsDigestService

            digest_context = await NewsDigestService.build_digest_context(
                session=self.session,
                user=user,
                num_topics=3,
                results_per_topic=3,
            )

            if not digest_context:
                logger.warning(
                    "News digest: no articles found for user {} — skipping send",
                    user.id,
                )
                return

            prompt = (
                "Here are today's fresh news articles personalised for me:\n\n"
                f"{digest_context}\n\n"
                "Please curate these results: pick the most relevant 4-6 articles "
                "based on my interests and goals from memory, briefly summarise each "
                "one (2-3 sentences), and add a short personal comment on why it "
                "might matter to me. Group by topic if helpful. Be concise and engaging."
            )

            await self._run_flow(
                user=user,
                prompt=prompt,
                greeting="\U0001f4f0 <b>Твой персональный дайджест новостей</b>",
                top_k=5,
            )
            logger.info("News digest sent to user {}", user.id)
        except Exception as e:
            logger.exception("Error sending news digest to user {}: {}", user.id, e)
            raise
