from google import genai
from ..config import settings
from ..models.facts import FactExtraction
from .episodic_memory_service import EpisodicMemoryService
from .core_memory_service import CoreMemoryService
from .working_memory_service import WorkingMemoryService
import logging
from pathlib import Path
import re
from sqlalchemy.ext.asyncio import AsyncSession

GEMMA_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "gemma_system.txt"

logger = logging.getLogger(__name__)

# instantiate a shared embeddings client and services that depend on it
from ..embeddings.gemini_embedding_client import GeminiEmbeddings

_emb_client = GeminiEmbeddings()
core_memory_service = CoreMemoryService(embeddings=_emb_client)
episodic_memory_service = EpisodicMemoryService(embeddings=_emb_client)
working_memory_service = WorkingMemoryService(embeddings=_emb_client)


class ExtractorService:
    """
    Service to extract important information from user messages using Gemma.
    """

    def __init__(self):
        self.client = genai.Client(api_key=settings.GEMMA_API_KEY)
        self.system_prompt = self._load_system_prompt()
        self.gemma_config = genai.types.GenerateContentConfig(
                temperature=0.0,
            )

    def _load_system_prompt(self) -> str:
        if GEMMA_PROMPT_PATH.exists():
            return GEMMA_PROMPT_PATH.read_text(encoding="utf-8")
        logger.warning("Gemma system prompt not found; using sipmle-default-dumb prompt")
        return (
            """You are a model that find and classifies personal information in text.
            Return the result in this JSON format:
            {
            "facts": [
                {
                "subject": "person or entity name",
                "relation": "simple verb phrase",
                "object": "target of relation",
                "importance": "High | Medium | Low"
                }
            ]
            }"""
        )
    
    async def find_write_important_info(self, user_id: int, session: AsyncSession, text: str) -> bool:
        """
        Uses Gemma to determine if the text contains important information and should be remembered.
        Returns True if important info is found and writed to memory, else False.
        """

        try:
            input_text = f"<SystemPrompt>{self.system_prompt}</SystemPrompt>\n\n{text}"
            response = await self.client.aio.models.generate_content(
                model=settings.GEMMA_MODEL_ID,
                contents=genai.types.Content(
                    role='user',
                    parts=[genai.types.Part.from_text(text=input_text)]
                ),
                config=self.gemma_config
            )
            
            if response and response.candidates:
                reply = response.candidates[0].content.parts[0].text
                try:
                    clean_json = re.sub(r"^```(?:json)?|```$", "", reply.strip(), flags=re.MULTILINE).strip()
                    extraction = FactExtraction.model_validate_json(clean_json)
                except Exception as e:
                    logger.error(f"Failed to parse Gemma extraction JSON: {e}")
                    return False
                facts = extraction.personal_information
                if facts:
                    try:
                        for item in facts:
                            if item.importance == "High":
                                await core_memory_service.store_core(
                                    session=session,
                                    user_id=user_id,
                                    fact_text = item.fact,
                                )
                                logger.info(f"Important fact extracted: {item.fact} (Importance: {item.importance})")
                            
                            if item.importance == "Medium":
                                await episodic_memory_service.store_episode(
                                    session=session,
                                    user_id=user_id,
                                    fact_text = item.fact,
                                )
                                logger.info(f"Episodic memory fact extracted: {item.fact} (Importance: {item.importance})")

                            if item.importance == "Low":
                                await working_memory_service.store_working(
                                    session=session,
                                    user_id=user_id,
                                    fact_text=item.fact
                                )
                                logger.info(f"Working memory fact extracted: {item.fact} (Importance: {item.importance})")
                        return True
                    except Exception as e:
                        logger.error(f"Failed to store extracted facts: {e}")
                        # Rollback the session to avoid PendingRollbackError
                        try:
                            await session.rollback()
                        except Exception as rollback_error:
                            logger.error(f"Failed to rollback session: {rollback_error}")
                        return False
        except Exception as e:
            logger.error(f"Gemma extraction failed: {e}")
            return False