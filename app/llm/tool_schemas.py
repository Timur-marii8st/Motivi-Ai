"""
Tool/function definitions for Gemini function calling.
"""

TOOL_CREATE_DOCX = {
    "name": "create_and_send_plan_document",
    "description": "Create a formatted .docx plan document with sections and send it to the user, then pin it.",
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Document title (e.g., 'Weekly Plan - Jan 15-21')"},
            "sections": {
                "type": "array",
                "description": "List of sections with heading and content",
                "items": {
                    "type": "object",
                    "properties": {
                        "heading": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["heading", "content"],
                },
            },
            "footer": {"type": "string", "description": "Optional footer text"},
        },
        "required": ["title", "sections"],
    },
}

TOOL_CREATE_TASK = {
    "name": "create_task",
    "description": "Create a new task for the user with title, description, and optional due date.",
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Task title"},
            "description": {"type": "string", "description": "Task description"},
            "due_date_iso": {"type": "string", "description": "ISO format due date (YYYY-MM-DDTHH:MM:SS) or null"},
        },
        "required": ["title"],
    },
}

SEND_TELEGRAM_MESSAGE_AND_PIN = {
    "name": "send_telegram_message_and_pin",
    "description": "Send an important message in the user's Telegram chat and pin it.",
    "parameters": {
        "type": "object",
        "properties": {
                "message_text": {"type": "string", "description": "Text of the message to send"},
        },
            "required": ["message_text"],
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

TOOL_LOG_HABIT = {
    "name": "log_habit_completion",
    "description": "Log that the user completed a habit today.",
    "parameters": {
        "type": "object",
        "properties": {
            "habit_id": {"type": "integer", "description": "Habit ID"},
            "count": {"type": "integer", "description": "Number of completions (default 1)"},
        },
        "required": ["habit_id"],
    },
}

ALL_TOOLS = [
    TOOL_CREATE_DOCX,
    TOOL_CREATE_TASK,
    SEND_TELEGRAM_MESSAGE_AND_PIN,
    TOOL_CREATE_CALENDAR_EVENT,
    TOOL_CHECK_AVAILABILITY,
    TOOL_LOG_HABIT, 
]