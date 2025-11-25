"""
Tool/function definitions for Gemini function calling.
"""

SEND_TELEGRAM_MESSAGE_AND_PIN = {
    "name": "send_telegram_message_and_pin",
    "description": "Send an important message in the user's Telegram chat and pin it.",
    "parameters": {
        "type": "object",
        "properties": {
            "message_text": {"type": "string", "description": "Text of the message to send"},
            "disable_notification": {"type": "boolean", "description": "Send silently without sound", "default": False},
        },
        "required": ["message_text"],
    },
}

TOOL_SCHEDULE_REMINDER = {
    "name": "schedule_reminder",
    "description": "Schedule a one-off motivational reminder message for the user at a specific datetime.",
    "parameters": {
        "type": "object",
        "properties": {
            "message_text": {"type": "string", "description": "Text of the reminder message to send"},
            "reminder_datetime_iso": {"type": "string", "description": "Exact datetime for the reminder in ISO format (YYYY-MM-DDTHH:MM:SS, in user's local time or UTC as specified)."},
        },
        "required": ["message_text", "reminder_datetime_iso"],
    },
}

TOOL_CREATE_CALENDAR_EVENT = {
    "name": "create_calendar_event",
    "description": "Create an event in the user's Google Calendar.",
    "parameters": {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "Event title"},
            "start_datetime": {"type": "string", "description": "Start datetime ISO format"},
            "end_datetime": {"type": "string", "description": "End datetime ISO format"},
            "description": {"type": "string", "description": "Event description"},
        },
        "required": ["summary", "start_datetime", "end_datetime"],
    },
}

TOOL_CHECK_AVAILABILITY = {
    "name": "check_calendar_availability",
    "description": "Check if the user is available during a time window.",
    "parameters": {
        "type": "object",
        "properties": {
            "start_datetime": {"type": "string", "description": "Start datetime ISO format"},
            "end_datetime": {"type": "string", "description": "End datetime ISO format"},
        },
        "required": ["start_datetime", "end_datetime"],
    },
}

ALL_TOOLS = [
    SEND_TELEGRAM_MESSAGE_AND_PIN,
    TOOL_SCHEDULE_REMINDER,
    TOOL_CREATE_CALENDAR_EVENT,
    TOOL_CHECK_AVAILABILITY,
]