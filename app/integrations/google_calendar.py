from __future__ import annotations
from __future__ import annotations

from typing import Optional, List, Dict, Any
from datetime import datetime

import asyncio
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.auth.transport.requests import Request
from loguru import logger

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ..models.oauth_token import OAuthToken
from ..utils.encryption import token_encryptor
from ..config import settings


SCOPES = ["https://www.googleapis.com/auth/calendar"]


class GoogleCalendarService:
    """Manage Google Calendar OAuth and operations."""

    @staticmethod
    def get_oauth_flow() -> Flow:
        """Create OAuth2 flow for Google Calendar."""
        client_config = {
            "web": {
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [settings.GOOGLE_REDIRECT_URI],
            }
        }

        flow = Flow.from_client_config(
            client_config, scopes=SCOPES, redirect_uri=settings.GOOGLE_REDIRECT_URI
        )
        return flow

    @staticmethod
    async def get_credentials(session: AsyncSession, user_id: int) -> Optional[Credentials]:
        """Retrieve and decrypt stored credentials for a user.

        Returns None when no token is stored or decryption/refresh fails.
        """
        result = await session.execute(
            select(OAuthToken).where(
                OAuthToken.user_id == user_id, OAuthToken.provider == "google_calendar"
            )
        )
        token_record = result.scalar_one_or_none()

        if not token_record:
            return None

        try:
            token_data = token_encryptor.decrypt(token_record.encrypted_token_blob)

            # token_encryptor may return bytes (e.g. JSON bytes) or a dict
            if isinstance(token_data, (bytes, str)):
                # lazy import to avoid circular deps in some setups
                import json

                token_data = json.loads(token_data)

            creds = Credentials(
                token=token_data.get("token"),
                refresh_token=token_data.get("refresh_token"),
                token_uri=token_data.get("token_uri"),
                client_id=token_data.get("client_id"),
                client_secret=token_data.get("client_secret"),
                scopes=token_data.get("scopes"),
            )

            # Refresh synchronously in a thread to avoid blocking the event loop
            if getattr(creds, "expired", False) and creds.refresh_token:
                try:
                    await asyncio.to_thread(creds.refresh, Request())
                    await GoogleCalendarService.store_credentials(session, user_id, creds)
                except Exception:
                    logger.exception("Failed to refresh Google credentials for user %s", user_id)
                    return None

            return creds
        except Exception:
            logger.exception("Failed to decrypt/refresh credentials for user %s", user_id)
            return None

    @staticmethod
    async def store_credentials(session: AsyncSession, user_id: int, creds: Credentials) -> None:
        """Encrypt and store credentials."""
        token_data: Dict[str, Any] = {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": creds.scopes,
        }

        # Ensure token_data is serializable by the encryptor
        encrypted_blob = token_encryptor.encrypt(token_data)

        result = await session.execute(
            select(OAuthToken).where(
                OAuthToken.user_id == user_id, OAuthToken.provider == "google_calendar"
            )
        )
        token_record = result.scalar_one_or_none()

        if token_record:
            token_record.encrypted_token_blob = encrypted_blob
            token_record.token_expiry = creds.expiry
            # token_record.touch() may be defined on the model; call if present
            if hasattr(token_record, "touch"):
                token_record.touch()
        else:
            token_record = OAuthToken(
                user_id=user_id,
                provider="google_calendar",
                encrypted_token_blob=encrypted_blob,
                token_expiry=creds.expiry,
            )
            session.add(token_record)

        await session.flush()
        logger.info("Stored Google Calendar credentials for user %s", user_id)

    @staticmethod
    async def create_event(
        session: AsyncSession,
        user_id: int,
        summary: str,
        start_dt: datetime,
        end_dt: datetime,
        description: Optional[str] = None,
        timezone: str = "UTC",
    ) -> Optional[str]:
        """Create a calendar event. Returns event ID or None on failure."""
        creds = await GoogleCalendarService.get_credentials(session, user_id)
        if not creds:
            logger.warning("No credentials for user %s", user_id)
            return None

        try:
            service = await asyncio.to_thread(build, "calendar", "v3", credentials=creds)

            event = {
                "summary": summary,
                "description": description or "",
                "start": {"dateTime": start_dt.isoformat(), "timeZone": timezone},
                "end": {"dateTime": end_dt.isoformat(), "timeZone": timezone},
            }

            created_event = await asyncio.to_thread(
                lambda: service.events().insert(calendarId="primary", body=event).execute()
            )
            event_id = created_event.get("id")
            logger.info("Created calendar event %s for user %s", event_id, user_id)
            return event_id

        except HttpError:
            logger.exception("Google Calendar API error while creating event for user %s", user_id)
            return None

    @staticmethod
    async def check_availability(
        session: AsyncSession,
        user_id: int,
        start_dt: datetime,
        end_dt: datetime,
        timezone: str = "UTC",
    ) -> bool:
        """Check if user is free during a time window. Returns True if available."""
        creds = await GoogleCalendarService.get_credentials(session, user_id)
        if not creds:
            return True  # Assume available if no calendar linked

        try:
            service = await asyncio.to_thread(build, "calendar", "v3", credentials=creds)

            # Google expects RFC3339 timestamps. If start_dt/end_dt are naive, use UTC.
            def _to_rfc3339(dt: datetime) -> str:
                if dt.tzinfo is None:
                    return dt.isoformat() + "Z"
                return dt.isoformat()

            body = {
                "timeMin": _to_rfc3339(start_dt),
                "timeMax": _to_rfc3339(end_dt),
                "timeZone": timezone,
                "items": [{"id": "primary"}],
            }

            freebusy = await asyncio.to_thread(lambda: service.freebusy().query(body=body).execute())
            busy = freebusy.get("calendars", {}).get("primary", {}).get("busy", [])

            is_available = len(busy) == 0
            logger.info("User %s availability %s-%s: %s", user_id, start_dt, end_dt, is_available)
            return is_available

        except HttpError:
            logger.exception("Freebusy check failed for user %s", user_id)
            return True  # Fail open

    @staticmethod
    async def list_upcoming_events(
        session: AsyncSession, user_id: int, max_results: int = 10, timezone: str = "UTC"
    ) -> List[Dict[str, Any]]:
        """List upcoming events."""
        creds = await GoogleCalendarService.get_credentials(session, user_id)
        if not creds:
            return []

        try:
            service = await asyncio.to_thread(build, "calendar", "v3", credentials=creds)

            now = datetime.utcnow().isoformat() + "Z"
            events_result = await asyncio.to_thread(
                lambda: service.events()
                .list(calendarId="primary", timeMin=now, maxResults=max_results, singleEvents=True, orderBy="startTime")
                .execute()
            )

            events = events_result.get("items", [])

            simplified: List[Dict[str, Any]] = []
            for event in events:
                start = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date")
                simplified.append(
                    {
                        "id": event.get("id"),
                        "summary": event.get("summary", "No title"),
                        "start": start,
                        "description": event.get("description", ""),
                    }
                )

            logger.info("Listed %s upcoming events for user %s", len(simplified), user_id)
            return simplified

        except HttpError:
            logger.exception("List events failed for user %s", user_id)
            return []