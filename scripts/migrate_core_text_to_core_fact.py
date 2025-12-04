import asyncio
import json
from datetime import datetime, timezone
from sqlmodel import select
from app.db import AsyncSessionLocal
from app.models.core_memory import CoreMemory, CoreFact, CoreFactEmbedding
from app.embeddings.gemini_embedding_client import GeminiEmbeddings
from loguru import logger


async def migrate():
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(CoreMemory))
        rows = result.scalars().all()
        emb = GeminiEmbeddings()
        for cm in rows:
            if not cm.core_text:
                continue
            try:
                parsed = json.loads(cm.core_text)
                if isinstance(parsed, list):
                    facts = parsed
                else:
                    facts = [{"fact": str(parsed), "created_at": cm.created_at.isoformat() if cm.created_at else None}]
            except Exception:
                facts = [{"fact": cm.core_text, "created_at": cm.created_at.isoformat() if cm.created_at else None}]

            # store facts
            for f in facts:
                created_at = None
                if isinstance(f, dict) and f.get("created_at"):
                    try:
                        created_at = datetime.fromisoformat(f["created_at"])
                    except Exception:
                        created_at = cm.created_at
                else:
                    created_at = cm.created_at

                cf = CoreFact(core_memory_id=cm.id, fact_text=f["fact"], created_at=created_at)
                session.add(cf)
                await session.flush()

                # create embedding
                try:
                    vec = await emb.embed(f["fact"], task_type="retrieval_document")
                    if vec:
                        cfe = CoreFactEmbedding(core_fact_id=cf.id, embedding=vec)
                        session.add(cfe)
                        await session.flush()
                except Exception as e:
                    logger.error("Failed to embed migrated fact {}: {}", cf.id, e)

        await session.commit()


if __name__ == "__main__":
    asyncio.run(migrate())
