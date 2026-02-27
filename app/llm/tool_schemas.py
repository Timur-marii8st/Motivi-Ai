"""
Tool/function definitions for OpenAI/OpenRouter function calling.
"""

def _to_openai_tool(schema: dict) -> dict:
    """Wraps a function schema in OpenAI's tool format."""
    return {
        "type": "function",
        "function": schema
    }

TOOL_SCHEDULE_REMINDER = {
    "name": "schedule_reminder",
    "description": "Schedule a one-off motivational reminder message for the user at a specific datetime. The time should be in user's local timezone.",
    "parameters": {
        "type": "object",
        "properties": {
            "message_text": {"type": "string", "description": "Text of the reminder message to send"},
            "reminder_datetime_iso": {"type": "string", "description": "Exact datetime for the reminder in ISO format (YYYY-MM-DDTHH:MM:SS). Use the user's local time. Example: 2025-11-26T15:30:00"},
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


TOOL_EXECUTE_CODE = {
    "name": "execute_code",
    "description": (
        "Execute a code snippet in an isolated sandbox and return the output. "
        "Use for running code, calculations, quick one-off plots, or logic demonstrations.\n\n"
        "IMPORTANT — for Word documents, Excel spreadsheets, PowerPoint presentations, "
        "data analysis charts, CVs, study plans, or project plans: "
        "call load_skill(name) FIRST to get proper code patterns. "
        "Only call execute_code after loading the relevant skill. "
        "Available skills are listed in the system prompt under 'Available Skills'.\n\n"
        "Supported languages: python, javascript, bash.\n\n"
        "PYTHON FILE OUTPUT:\n"
        "  Files saved to /output/ inside the sandbox are sent to the user automatically via Telegram.\n"
        "  Always save to /output/ — never call plt.show().\n"
        "  Quick example (simple inline chart — no skill needed for this):\n"
        "    import matplotlib; matplotlib.use('Agg')\n"
        "    import matplotlib.pyplot as plt\n"
        "    plt.plot([1, 2, 3, 4]); plt.title('Chart')\n"
        "    plt.savefig('/output/chart.png'); plt.close()\n\n"
        "Sandbox: no network, 30s timeout, 256 MB RAM, read-only root FS. "
        "Do NOT use for malicious, harmful, or privacy-violating code.\n\n"
        "When output_files_sent is in the tool result, files were already delivered to the user. "
        "In your reply just mention the filename(s) — do NOT describe their contents."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "language": {
                "type": "string",
                "enum": ["python", "javascript", "bash"],
                "description": "Programming language of the code snippet.",
            },
            "code": {
                "type": "string",
                "description": (
                    "The source code to execute. "
                    "For Python file output, save files to /output/ (e.g. plt.savefig('/output/chart.png')). "
                    "Never call plt.show() — use savefig instead."
                ),
            },
        },
        "required": ["language", "code"],
    },
}

TOOL_LOAD_SKILL = {
    "name": "load_skill",
    "description": (
        "Load detailed step-by-step instructions for a specialist skill. "
        "Call this BEFORE attempting any task that matches an available skill listed in the system prompt. "
        "The returned instructions contain working code patterns and best practices — "
        "use them to guide the subsequent execute_code call. "
        "Do not attempt skill-based tasks from memory; always load the skill first."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Exact skill name as listed in the 'Available Skills' section of the system prompt.",
            },
        },
        "required": ["name"],
    },
}


RAW_TOOLS = [
    TOOL_SCHEDULE_REMINDER,
    TOOL_CANCEL_REMINDER,
    TOOL_LIST_REMINDERS,
    TOOL_CREATE_PLAN,
    TOOL_CHECK_PLAN,
    TOOL_EDIT_PLAN,
    TOOL_CREATE_CALENDAR_EVENT,
    TOOL_CHECK_AVAILABILITY,
    TOOL_EXECUTE_CODE,
    TOOL_LOAD_SKILL,
]

ALL_TOOLS = [_to_openai_tool(t) for t in RAW_TOOLS]