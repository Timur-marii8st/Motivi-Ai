import asyncio
from app.db import get_session
from app.models.users import User
from app.services.episodic_memory_service import EpisodicMemoryService
from app.embeddings.gemini_embedding_client import GeminiEmbeddings
from app.jobs.weekly_summary import generate_weekly_summary_for_user
from sqlmodel import select

async def main():
    async with get_session() as session:
        result = await session.execute(select(User))
        users = result.scalars().all()
        
        gemini_embeddings = GeminiEmbeddings()
        episodic = EpisodicMemoryService(gemini_embeddings)
        
        for user in users:
            await generate_weekly_summary_for_user(session, user, episodic)
        
        await gemini_embeddings.aclose()

if __name__ == "__main__":
    asyncio.run(main())