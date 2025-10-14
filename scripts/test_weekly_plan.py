import asyncio
from app.db import get_session
from app.models.users import User
from sqlmodel import select

async def main():
    from app.scheduler.jobs import weekly_plan_job
    
    async with get_session() as session:
        result = await session.execute(select(User).limit(1))
        user = result.scalar_one_or_none()
        
        if user:
            await weekly_plan_job(user.id)

if __name__ == "__main__":
    asyncio.run(main())