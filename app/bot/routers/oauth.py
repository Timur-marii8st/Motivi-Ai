from __future__ import annotations
from aiogram import Router, F
from aiogram.types import Message
from loguru import logger

from ...integrations.google_calendar import GoogleCalendarService
from ...services.profile_services import get_or_create_user
from ...services.oauth_state_service import OAuthStateService

router = Router(name="oauth")

@router.message(F.text == "/connect_calendar")
async def connect_calendar_cmd(message: Message, session):
    """
    Initiates the secure Google Calendar OAuth flow.
    """
    user = await get_or_create_user(session, message.from_user.id, message.chat.id)
    
    # 1. Create a secure state token and store user info in Redis
    try:
        state_token = await OAuthStateService.create_and_store_state(
            user_id=user.id,
            chat_id=message.chat.id
        )
    except Exception as e:
        logger.exception("Failed to create OAuth state in Redis: {}", e)
        await message.answer("❌ Could not start the connection process. Please try again later.")
        return

    # 2. Generate the authorization URL with the state token
    flow = GoogleCalendarService.get_oauth_flow()
    auth_url, _ = flow.authorization_url(
        access_type='offline',  # Request a refresh token
        prompt='consent',       # Ensure the user is prompted for consent
        state=state_token       # Include the secure state token
    )
    
    # 3. Send the URL to the user
    await message.answer(
        "🔗 To connect your Google Calendar, please click the link below.\n\n"
        "I will notify you once the connection is complete.\n\n"
        f"<a href='{auth_url}'><b>Authorize with Google</b></a>"
    )