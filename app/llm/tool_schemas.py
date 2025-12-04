"""
Tool/function definitions for Gemini function calling.
"""

TOOL_SCHEDULE_REMINDER = {
    "name": "schedule_reminder",
    "description": "Schedule a one-off motivational reminder message for the user at a specific datetime in UTC.",
    "parameters": {
        "type": "object",
        "properties": {
            "message_text": {"type": "string", "description": "Text of the reminder message to send"},
            "reminder_datetime_iso": {"type": "string", "description": "Exact datetime for the reminder in ISO format (YYYY-MM-DDTHH:MM:SS) in UTC timezone. Example: 2025-11-26T15:30:00"},
        },
        "required": ["message_text", "reminder_datetime_iso"],
    },
}

TOOL_CANCEL_REMINDER = {
    "name": "cancel_reminder",
    "description": "Cancel a scheduled reminder created with schedule_reminder tool.",
    "parameters": {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "The job_id returned when the reminder was scheduled"},
        },
        "required": ["job_id"],
    },
}

TOOL_LIST_REMINDERS = {
    "name": "list_reminders",
    "description": "List all active scheduled reminders for the user.",
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

TOOL_CREATE_PLAN = {
    "name": "create_plan",
    "description": "Create a plan for the user (daily, weekly, or monthly) and send it as a message. The plan will be stored in memory for the specified duration.",
    "parameters": {
        "type": "object",
        "properties": {
            "plan_level": {
                "type": "string",
                "enum": ["daily", "weekly", "monthly"],
                "description": "The time scope of the plan: 'daily' (stored for 1 day), 'weekly' (stored for 7 days), or 'monthly' (stored for 30 days)"
            },
            "plan_content": {"type": "string", "description": "The plan content to send to the user and store in memory"},
        },
        "required": ["plan_level", "plan_content"],
    },
}

TOOL_CHECK_PLAN = {
    "name": "check_plan",
    "description": "Check which active plans are currently stored for the user.",
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

TOOL_EDIT_PLAN = {
    "name": "edit_plan",
    "description": "Edit an existing plan that was created with create_plan. You can update the plan content and/or extend its expiration time.",
    "parameters": {
        "type": "object",
        "properties": {
            "plan_id": {"type": "integer", "description": "The ID of the plan to edit"},
            "plan_content": {"type": "string", "description": "The new plan content to send to the user and store"},
            "extend_expiry": {
                "type": "boolean",
                "description": "If true, extends the expiry date based on the original plan level from now. Default is false."
            },
        },
        "required": ["plan_id", "plan_content"],
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
    TOOL_SCHEDULE_REMINDER,
    TOOL_CANCEL_REMINDER,
    TOOL_LIST_REMINDERS,
    TOOL_CREATE_PLAN,
    TOOL_CHECK_PLAN,
    TOOL_EDIT_PLAN,
    TOOL_CREATE_CALENDAR_EVENT,
    TOOL_CHECK_AVAILABILITY,
]