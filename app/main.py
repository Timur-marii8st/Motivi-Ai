from __future__ import annotations
from typing import Any, Dict, AsyncIterator
from fastapi import FastAPI, Request, Header, HTTPException, Depends
from fastapi.responses import JSONResponse
from aiogram.types import Update
from loguru import logger
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import init_db
from .bot.dispatcher import create_bot_and_dispatcher
from .scheduler.scheduler_instance import start_scheduler, shutdown_scheduler, scheduler

from .services.oauth_state_service import OAuthStateService
from .integrations.google_calendar import GoogleCalendarService
from .db import get_session

from .models.users import User
from .models.episode import Episode


bot, dp = create_bot_and_dispatcher()


async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # --- startup ---
    logger.remove()
    logger.add(lambda msg: print(msg, end=""), level=settings.LOG_LEVEL)
    
    await init_db()
    start_scheduler()

    webhook_url = f"{settings.PUBLIC_BASE_URL}/telegram/webhook"
    await bot.set_webhook(url=webhook_url, secret_token=settings.TELEGRAM_WEBHOOK_SECRET)
    logger.info(f"Webhook set to {webhook_url}")
    logger.info("Motivi_AI started successfully")

    # Передаём управление FastAPI (запуск приложения)
    yield

    # --- shutdown ---
    shutdown_scheduler()
    try:
        await bot.delete_webhook()
    except Exception:
        pass
    logger.info("Motivi_AI shut down")


app = FastAPI(title="Motivi_AI", lifespan=lifespan)

@app.get("/oauth/google/callback")
async def oauth_google_callback(code: str, state: str):
    """
    Handles the OAuth callback from Google.
    """
    logger.info("Received Google OAuth callback with state: {}", state)
    
    # 1. Verify the state token
    user_info = await OAuthStateService.verify_and_consume_state(state)
    if not user_info:
        logger.warning("Invalid or expired OAuth state token received: {}", state)
        raise HTTPException(status_code=400, detail="Invalid or expired session. Please try again.")

    user_id = user_info["user_id"]
    chat_id = user_info["chat_id"]
    
    # 2. Exchange the authorization code for credentials
    try:
        flow = GoogleCalendarService.get_oauth_flow()
        # The redirect_uri must match the one used in the auth URL
        flow.fetch_token(code=code)
        creds = flow.credentials
        
        # 3. Store the credentials securely
        async with get_session() as session:
            await GoogleCalendarService.store_credentials(session, user_id, creds)
            await session.commit()
        
        logger.info("Successfully stored Google Calendar credentials for user {}", user_id)
        
        # 4. Notify the user in Telegram
        await bot.send_message(
            chat_id,
            "✅ Google Calendar connected successfully! I can now help you manage your events."
        )
        
        return JSONResponse(
            {"status": "success"},
            status_code=200,
            # You can redirect to a simple success page here
            # headers={"Location": "https://your-domain.com/oauth-success"}
        )

    except Exception as e:
        logger.exception("OAuth callback token exchange failed for user {}: {}", user_id, e)
        await bot.send_message(
            chat_id,
            f"❌ Authorization failed during token exchange: {e}\nPlease try connecting again."
        )
        raise HTTPException(status_code=500, detail="Failed to exchange authorization code for token.")


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "scheduler_running": scheduler.running if scheduler else False,
        "jobs_count": len(scheduler.get_jobs()) if scheduler and scheduler.running else 0,
    }


@app.get("/metrics")
async def metrics(session: AsyncSession = Depends(get_session)):
    """Basic metrics endpoint."""
    if not settings.ENABLE_METRICS:
        raise HTTPException(status_code=404)
    
    from sqlmodel import select, func
    
    user_count = (await session.execute(select(func.count(User.id)))).scalar_one()
    episode_count = (await session.execute(select(func.count(Episode.id)))).scalar_one()
    
    return {
        "total_users": user_count,
        "total_episodes": episode_count,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    if x_telegram_bot_api_secret_token != settings.TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret token")

    data: Dict[str, Any] = await request.json()
    update = Update.model_validate(data)
    await dp.feed_update(bot, update)
    return JSONResponse({"ok": True})
