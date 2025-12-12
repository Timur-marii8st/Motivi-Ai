from ..config import settings
from ..models.facts import FactExtraction
from .episodic_memory_service import EpisodicMemoryService
from .core_memory_service import CoreMemoryService
from .working_memory_service import WorkingMemoryService
from ..embeddings.gemini_embedding_client import GeminiEmbeddings
from ..llm.client import async_client
import logging
from pathlib import Path
import re
from sqlalchemy.ext.asyncio import AsyncSession

GEMMA_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "gemma_system.txt"

logger = logging.getLogger(__name__)

# instantiate a shared embeddings client and services that depend on it
_emb_client = GeminiEmbeddings()
core_memory_service = CoreMemoryService(embeddings=_emb_client)
episodic_memory_service = EpisodicMemoryService(embeddings=_emb_client)
working_memory_service = WorkingMemoryService(embeddings=_emb_client)


class ExtractorService:
    """
    Service to extract important information from user messages using OpenRouter (Gemma).
    """

    def __init__(self):
        self.client = async_client
        self.system_prompt = self._load_system_prompt()
        self.model = settings.EXTRACTOR_MODEL_ID

    def _load_system_prompt(self) -> str:
        if GEMMA_PROMPT_PATH.exists():
            return GEMMA_PROMPT_PATH.read_text(encoding="utf-8")
        return "You are a model that finds and classifies personal information in text."

    async def find_write_important_info(self, user_id: int, session: AsyncSession, text: str) -> bool:
        """
        Uses OpenRouter/Gemma to determine if the text contains important information and should be remembered.
        Returns True if important info is found and written to memory, else False.
        """

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": text}
                ],
                temperature=0.0,
                extra_body={
                    "response_format": {"type": "json_object"} 
                }
            )
            
            reply = response.choices[0].message.content
            
            try:
                # Basic cleanup for markdown json blocks if model adds them
                clean_json = re.sub(r"^```(?:json)?|```$", "", reply.strip(), flags=re.MULTILINE).strip()
                extraction = FactExtraction.model_validate_json(clean_json)
            except Exception as e:
                logger.error(f"Failed to parse extraction JSON: {e}")
                return False

            facts = extraction.personal_information
            if facts:
                try:
                    for item in facts:
                        if item.importance == "Core":
                            await core_memory_service.store_core(session=session, user_id=user_id, fact_text=item.fact)
                            logger.info(f"Important fact extracted: {item.fact} (Importance: {item.importance})")
                        
                        if item.importance == "Episode":
                            await episodic_memory_service.store_episode(session=session, user_id=user_id, fact_text=item.fact)
                            logger.info(f"Episodic memory fact extracted: {item.fact} (Importance: {item.importance})")

                        if item.importance == "Working":
                            await working_memory_service.store_working(session=session, user_id=user_id, fact_text=item.fact)
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
            logger.error(f"Extraction failed: {e}")
            return False