from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.triggers.date import DateTrigger
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..embeddings.gemini_embedding_client import GeminiEmbeddings
from ..llm.client import async_client
from ..models.settings import UserSettings
from ..models.users import User
from ..scheduler.scheduler_instance import scheduler, start_scheduler
from .conversation_history_service import ConversationHistoryService
from .core_memory_service import CoreMemoryService
from .episodic_memory_service import EpisodicMemoryService
from .memory_orchestrator import MemoryOrchestrator
from .working_memory_service import WorkingMemoryService


ALLOWED_TOUCH_TYPES = {"reflection", "daily_plan", "followup", "news_digest", "custom"}
PLANNER_JOB_PREFIX = "proactive_planner"
TOUCH_JOB_PREFIX = "proactive_touch"

_shared_embeddings = GeminiEmbeddings()


@dataclass(frozen=True)
class ProactiveTouch:
    send_at_local: datetime
    touch_type: str
    priority: str
    reason: str
    prompt: str


class ProactivePlanningService:
    """LLM-driven planner for proactive user touches.

    The LLM proposes a schedule. This service validates that proposal and
    schedules actual jobs, keeping the deterministic guardrails in Python.
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self.client = async_client
        self.memory_orchestrator = MemoryOrchestrator(
            EpisodicMemoryService(_shared_embeddings),
            CoreMemoryService(_shared_embeddings),
            WorkingMemoryService(_shared_embeddings),
        )

    async def plan_and_schedule(self, user: User, user_settings: UserSettings) -> list[str]:
        if not getattr(user_settings, "enable_smart_proactivity", True):
            logger.info("Smart proactivity disabled for user {}", user.id)
            self.remove_pending_touches(user.id)
            return []
        if not user.user_timezone:
            logger.info("User {} has no timezone; skipping proactive planning", user.id)
            return []

        tz = ZoneInfo(user.user_timezone)
        now_local = datetime.now(tz)
        planner_query = (
            "Decide whether and when to proactively message this user today or tomorrow. "
            "Focus only on useful reflection, daily planning, or follow-up touches."
        )
        memory_pack = await self.memory_orchestrator.assemble(
            self.session,
            user,
            planner_query,
            top_k=8,
        )
        history = await ConversationHistoryService.get_history(user.tg_chat_id)
        decision = await self._ask_planner_llm(
            user=user,
            user_settings=user_settings,
            memory_context=memory_pack.to_context_dict(),
            recent_history=history[-12:],
            now_local=now_local,
        )
        touches = self._parse_touches(decision, now_local)
        scheduled_ids = self.schedule_touches(
            user=user,
            user_settings=user_settings,
            touches=touches,
            now_local=now_local,
        )
        logger.info("Scheduled {} proactive touch(es) for user {}", len(scheduled_ids), user.id)
        return scheduled_ids

    async def _ask_planner_llm(
        self,
        *,
        user: User,
        user_settings: UserSettings,
        memory_context: dict[str, Any],
        recent_history: list[dict[str, Any]],
        now_local: datetime,
    ) -> dict[str, Any]:
        max_per_day = getattr(user_settings, "proactive_max_messages_per_day", 1) or 1
        system_prompt = (
            "You are a scheduling policy model for a proactive Telegram planning assistant. "
            "You do not write user-facing messages. You only decide whether the assistant "
            "should send a small, useful proactive touch today or tomorrow.\n\n"
            "Return ONLY valid JSON. No markdown, no comments.\n\n"
            "Rules:\n"
            "- Prefer silence unless a message is likely to be genuinely useful.\n"
            "- Do not create morning/evening rituals or generic check-ins.\n"
            "- Good reasons: reflection after a meaningful day, a lightweight plan before focused work, "
            "a follow-up on something the user explicitly cared about.\n"
            "- Avoid guilt, pressure, hype, insults, or therapy-like language.\n"
            "- Never schedule during likely sleep time. Use the user profile if available.\n"
            f"- Schedule at most {max_per_day} message(s) per local day.\n"
            "- Allowed types: reflection, daily_plan, followup, news_digest, custom.\n\n"
            "JSON schema:\n"
            "{\n"
            '  "messages": [\n'
            "    {\n"
            '      "send_at_local": "YYYY-MM-DDTHH:MM:SS",\n'
            '      "type": "reflection|daily_plan|followup|news_digest|custom",\n'
            '      "priority": "low|medium|high",\n'
            '      "reason": "short internal reason",\n'
            '      "prompt": "instruction for the assistant when the message fires"\n'
            "    }\n"
            "  ]\n"
            "}\n"
        )
        user_payload = {
            "now_local": now_local.isoformat(timespec="seconds"),
            "timezone": user.user_timezone,
            "user_profile": {
                "id": user.id,
                "wake_time": user.wake_time.isoformat() if user.wake_time else None,
                "bed_time": user.bed_time.isoformat() if user.bed_time else None,
                "occupation": user.occupation_json,
            },
            "memory_context": memory_context,
            "recent_conversation": recent_history,
        }

        response = await self.client.chat.completions.create(
            model=settings.LLM_MODEL_ID,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            temperature=0.2,
            max_tokens=1200,
        )
        raw = response.choices[0].message.content or "{}"
        try:
            return json.loads(self._clean_json(raw))
        except json.JSONDecodeError:
            logger.warning("Planner LLM returned invalid JSON for user {}: {}", user.id, raw[:500])
            return {"messages": []}

    @staticmethod
    def _clean_json(value: str) -> str:
        value = value.strip()
        value = re.sub(r"^```(?:json)?", "", value, flags=re.IGNORECASE).strip()
        value = re.sub(r"```$", "", value).strip()
        return value

    def _parse_touches(self, decision: dict[str, Any], now_local: datetime) -> list[ProactiveTouch]:
        raw_messages = decision.get("messages", [])
        if not isinstance(raw_messages, list):
            return []

        touches: list[ProactiveTouch] = []
        horizon = now_local + timedelta(days=2)
        for item in raw_messages:
            if not isinstance(item, dict):
                continue
            try:
                send_at = datetime.fromisoformat(str(item["send_at_local"]))
            except (KeyError, ValueError, TypeError):
                continue
            if send_at.tzinfo is not None:
                send_at = send_at.astimezone(now_local.tzinfo).replace(tzinfo=None)
            local_with_tz = send_at.replace(tzinfo=now_local.tzinfo)
            if local_with_tz <= now_local + timedelta(minutes=10):
                continue
            if local_with_tz > horizon:
                continue

            touch_type = str(item.get("type", "custom")).strip().lower()
            if touch_type not in ALLOWED_TOUCH_TYPES:
                touch_type = "custom"
            prompt = str(item.get("prompt", "")).strip()
            if len(prompt) < 20:
                continue
            touches.append(
                ProactiveTouch(
                    send_at_local=local_with_tz,
                    touch_type=touch_type,
                    priority=str(item.get("priority", "low")).strip().lower() or "low",
                    reason=str(item.get("reason", "")).strip()[:400],
                    prompt=prompt[:2000],
                )
            )
        return sorted(touches, key=lambda touch: touch.send_at_local)

    def schedule_touches(
        self,
        *,
        user: User,
        user_settings: UserSettings,
        touches: list[ProactiveTouch],
        now_local: datetime,
    ) -> list[str]:
        max_per_day = max(0, min(int(getattr(user_settings, "proactive_max_messages_per_day", 1) or 1), 3))
        if max_per_day == 0:
            self.remove_pending_touches(user.id)
            return []

        self.remove_pending_touches(user.id)
        try:
            if not scheduler.running:
                start_scheduler()
        except Exception:
            logger.debug("Could not ensure scheduler was running before proactive scheduling")

        scheduled_ids: list[str] = []
        per_day: dict[str, int] = {}
        for touch in touches:
            if self._is_quiet_time(user, touch.send_at_local):
                continue
            day_key = touch.send_at_local.date().isoformat()
            if per_day.get(day_key, 0) >= max_per_day:
                continue
            per_day[day_key] = per_day.get(day_key, 0) + 1
            slot = len(scheduled_ids) + 1
            job_id = f"{TOUCH_JOB_PREFIX}_{user.id}_{touch.send_at_local:%Y%m%d%H%M}_{slot}"
            scheduler.add_job(
                func="app.scheduler.jobs:proactive_touch_job",
                trigger=DateTrigger(
                    run_date=touch.send_at_local.astimezone(timezone.utc),
                    timezone=timezone.utc,
                ),
                id=job_id,
                args=[user.id, touch.touch_type, touch.prompt, touch.reason],
                replace_existing=True,
            )
            scheduled_ids.append(job_id)
            logger.info(
                "Scheduled proactive touch {} for user {} at {} ({})",
                job_id,
                user.id,
                touch.send_at_local.isoformat(),
                touch.touch_type,
            )
        return scheduled_ids

    @staticmethod
    def _is_quiet_time(user: User, local_dt: datetime) -> bool:
        if user.wake_time and user.bed_time:
            wake = user.wake_time
            bed = user.bed_time
            current = local_dt.time()
            if wake < bed:
                return current < wake or current >= bed
            return current >= bed or current < wake

        default_start = time(hour=8, minute=0)
        default_end = time(hour=22, minute=0)
        current = local_dt.time()
        return current < default_start or current >= default_end

    @staticmethod
    def remove_pending_touches(user_id: int) -> None:
        prefix = f"{TOUCH_JOB_PREFIX}_{user_id}_"
        for job in scheduler.get_jobs():
            if job.id.startswith(prefix):
                scheduler.remove_job(job.id)

