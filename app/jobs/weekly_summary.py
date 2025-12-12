from __future__ import annotations
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from loguru import logger
import json

from ..models.users import User
from ..services.working_memory_service import WorkingMemoryService
from ..services.episodic_memory_service import EpisodicMemoryService
from ..llm.client import async_client
from ..config import settings

async def generate_weekly_summary_for_user(session: AsyncSession, user: User, episodic_service: EpisodicMemoryService):
    """
    Summarize the past week's episodes and refresh working memory.
    Called by scheduler (Phase 3) or manually.
    """
    # Fetch past 7 days of episodes
    episodes = await episodic_service.get_recent_episodes(session, user.id, limit=30)
    
    if not episodes:
        logger.info("No episodes for user {} to summarize", user.id)
        return

    # Build summary prompt
    episode_texts = "\n".join([f"- [{ep.type}] {ep.text}" for ep in episodes[:20]])
    prompt = (
        f"Summarize the following week's events for {user.name} into a concise focus summary (2–3 sentences) "
        f"and extract 3–5 short-term goals as a JSON array.\n\nEvents:\n{episode_texts}\n\n"
        f"Return JSON: {{\"summary\": \"...\", \"goals\": [\"goal1\", \"goal2\", ...]}}"
    )

    try:
        response = await async_client.chat.completions.create(
            model=settings.LLM_MODEL_ID,
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            extra_body={
                "response_format": {"type": "json_object"}
            }
        )
        response_text = response.choices[0].message.content
        data = json.loads(response_text) if response_text else {}
        summary_text = data.get("summary", "Focused on daily tasks and routines.")
        goals = data.get("goals", [])
    except Exception as e:
        logger.error("Weekly summary generation failed for user {}: {}", user.id, e)
        summary_text = "Continuing to build productive habits."
        goals = []

    # Refresh working memory
    await WorkingMemoryService.refresh_weekly(
        session, user.id, summary_text, {"goals": goals, "updated": datetime.now(timezone.utc).isoformat()}
    )
    logger.info("Weekly summary refreshed for user {}", user.id)