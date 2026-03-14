# CLAUDE.md — Motivi_AI Codebase Guide

This file provides context for AI assistants working on this codebase.

## Project Overview

**Motivi_AI** is a proactive Telegram planning assistant powered by LLMs. It uses a cognitive memory architecture (Core, Working, and Episodic memory) with RAG-based retrieval, habit tracking, Google Calendar integration, sandboxed code execution, web search, agent skills, a read-only Telegram userbot for channel monitoring, and autonomous scheduled interactions (morning/evening check-ins, weekly reviews, personalised news digests, custom user triggers).

The bot is built with **Python 3.11**, **Aiogram 3.x** (Telegram framework), and **FastAPI** (webhook server). All LLM calls go through **OpenRouter** using the OpenAI-compatible Python client.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11 |
| Telegram Framework | Aiogram 3.x |
| Web Server | FastAPI + Uvicorn |
| Database | PostgreSQL 16 + pgvector extension |
| ORM | SQLModel + SQLAlchemy 2.x (async) |
| Async DB Driver | asyncpg |
| LLM API | OpenRouter (OpenAI-compatible client) |
| Embeddings | Qwen3-embedding-8b via OpenRouter (`GeminiEmbeddings` class, misleadingly named) |
| Main LLM | Grok (via OpenRouter, configurable via `LLM_MODEL_ID`) |
| Audio/Image LLM | Gemini 2.0 Flash Lite via OpenRouter (`AUDIO_IMAGE_MODEL_ID`) |
| Extractor LLM | Gemma 3n via OpenRouter (`EXTRACTOR_MODEL_ID`) |
| Web Search | Tavily API (via `SearchService`) |
| MTProto Client | Telethon (read-only userbot for channel/DM monitoring) |
| Scheduling | APScheduler 3.x (AsyncIO) |
| FSM State Storage | Redis (via aiogram's RedisStorage) |
| Conversation History | Redis |
| Encryption | Google Tink (AEAD/AES256-GCM) + Fernet |
| Dependency Management | Poetry |
| Infrastructure | Docker Compose |
| Linting | Ruff |
| Formatting | Black |
| Type Checking | mypy |
| Testing | pytest |

---

## Repository Structure

```
Motivi-Ai/
├── app/                        # Main application package
│   ├── main.py                 # FastAPI app entry point, webhook endpoint, lifespan
│   ├── config.py               # Pydantic Settings (env-driven config), singleton `settings`
│   ├── db.py                   # SQLAlchemy engine, session factory, init_db()
│   ├── bot/
│   │   ├── dispatcher.py       # Bot + Dispatcher factory, middleware and router registration
│   │   ├── routers/            # Aiogram routers (one per feature domain)
│   │   │   ├── chat.py         # Main message handler (natural language → LLM)
│   │   │   ├── onboarding.py   # /start flow (FSM-based)
│   │   │   ├── habits.py       # /habits, /add_habit (inline keyboard for logging)
│   │   │   ├── profile.py      # /profile, account deletion
│   │   │   ├── settings.py     # /settings (toggle proactive flows, break mode)
│   │   │   ├── subscription.py # /subscribe, Telegram Stars payments
│   │   │   ├── oauth.py        # /connect_calendar
│   │   │   ├── multimodal.py   # Voice notes + photo handling
│   │   │   ├── admin.py        # Admin-only commands
│   │   │   ├── break_mode.py   # /break command
│   │   │   ├── group.py        # Group/supergroup message handling
│   │   │   ├── triggers.py     # /triggers, /add_trigger (custom proactive flows)
│   │   │   ├── userbot.py      # /connect_userbot, /disconnect_userbot, /userbot_interests
│   │   │   └── common.py       # Fallback / unknown command handler
│   │   ├── middlewares/
│   │   │   └── db_session.py   # Injects async DB session into handler data
│   │   ├── init.py             # Bot command registration
│   │   └── states.py           # Aiogram FSM state groups (Onboarding, HabitCreation, TriggerCreation, UserBotSetup)
│   ├── llm/
│   │   ├── client.py           # AsyncOpenAI client singleton (points to OpenRouter)
│   │   ├── conversation_service.py  # ReAct loop: LLM call → tool dispatch → response
│   │   ├── tool_schemas.py     # OpenAI function-calling tool definitions (ALL_TOOLS)
│   │   └── gemini_client.py    # Secondary LLM client for audio/image tasks
│   ├── services/               # Business logic layer
│   │   ├── memory_orchestrator.py      # Assembles MemoryPack (Core + Working + Episodic)
│   │   ├── core_memory_service.py      # Permanent facts (CoreFact) CRUD + vector retrieval
│   │   ├── episodic_memory_service.py  # Episode storage + RAG retrieval
│   │   ├── working_memory_service.py   # Short-term context, summaries with decay
│   │   ├── extractor_service.py        # LLM-based fact/episode extraction from messages
│   │   ├── fact_cleanup_service.py     # Deduplication of core facts by cosine similarity
│   │   ├── tool_executor.py            # Dispatches LLM tool calls to actual implementations
│   │   ├── conversation_history_service.py  # Redis-backed conversation history
│   │   ├── habit_service.py            # Habit CRUD, streak tracking, reminders
│   │   ├── proactive_flows.py          # Morning/Evening/Weekly/Monthly/News check-in orchestration
│   │   ├── profile_services.py         # get_or_create_user, profile updates
│   │   ├── account_service.py          # Account deletion (GDPR)
│   │   ├── oauth_state_service.py      # OAuth state token management (Redis)
│   │   ├── settings_service.py         # UserSettings CRUD
│   │   ├── stt_service.py              # Speech-to-text (Whisper via faster-whisper)
│   │   ├── vision_service.py           # Image analysis
│   │   ├── subscription_service.py     # Telegram Stars subscription logic
│   │   ├── profile_completeness_service.py  # Tracks user question/interaction counts
│   │   ├── code_executor_service.py    # Sandboxed Docker code execution with file output
│   │   ├── skills_service.py           # Agent Skills: load metadata + full instructions from .md files
│   │   ├── search_service.py           # Tavily web search with Redis caching + rate limiting
│   │   ├── news_digest_service.py      # Personalised news digest from user profile + core memory
│   │   ├── user_trigger_service.py     # Custom user trigger CRUD (max 5 per user)
│   │   ├── userbot_manager.py          # Telethon client lifecycle (start/stop/registry)
│   │   └── userbot_monitor.py          # Telethon event handlers: channel posts + DM reply suggestions
│   ├── models/                 # SQLModel table definitions
│   │   ├── users.py            # User (main table, encrypted name/occupation)
│   │   ├── core_memory.py      # CoreMemory + CoreFact (with vector embedding)
│   │   ├── working_memory.py   # WorkingMemory + WorkingMemoryEntry
│   │   ├── episode.py          # Episode + EpisodeEmbedding (pgvector)
│   │   ├── habit.py            # Habit + HabitLog
│   │   ├── settings.py         # UserSettings (proactive flow toggles, userbot settings)
│   │   ├── oauth_token.py      # Google OAuth credentials (encrypted)
│   │   ├── plan.py             # Plan (daily/weekly/monthly, time-expiring)
│   │   ├── facts.py            # CoreFact model
│   │   ├── profile_completeness.py  # ProfileCompleteness tracking
│   │   ├── user_trigger.py     # UserTrigger (custom cron-scheduled proactive prompts)
│   │   └── userbot_session.py  # UserBotSession (encrypted Telethon StringSession)
│   ├── skills/                 # Agent Skill instruction files (Markdown with YAML frontmatter)
│   │   ├── cv-resume.md
│   │   ├── data-analysis.md
│   │   ├── excel-spreadsheet.md
│   │   ├── powerpoint-presentation.md
│   │   ├── project-planner.md
│   │   ├── study-planner.md
│   │   └── word-document.md
│   ├── scheduler/
│   │   ├── scheduler_instance.py  # APScheduler singleton
│   │   ├── job_manager.py         # Per-user job scheduling (morning/evening/weekly/monthly/news/triggers)
│   │   └── jobs.py                # Job functions called by APScheduler
│   ├── jobs/
│   │   └── weekly_summary.py      # Weekly memory summarization job
│   ├── security/
│   │   ├── encryption_manager.py  # Google Tink AEAD encryptor singleton
│   │   └── encrypted_types.py     # SQLAlchemy TypeDecorators: EncryptedTextType, EncryptedJSONType
│   ├── embeddings/
│   │   └── gemini_embedding_client.py  # GeminiEmbeddings class (calls OpenRouter embedding API)
│   ├── integrations/
│   │   └── google_calendar.py     # Google Calendar OAuth flow + event management
│   ├── middleware/
│   │   └── rate_limit.py          # Per-user rate limiting middleware (Redis-backed)
│   ├── prompts/
│   │   ├── moti_system.txt        # Main system prompt (Russian)
│   │   ├── moti_system_eng.txt    # Main system prompt (English)
│   │   ├── gemma_system.txt       # Extractor prompt (Russian)
│   │   └── gemma_system_eng.txt   # Extractor prompt (English)
│   └── utils/
│       ├── get_user_time.py       # Helper: current time in user's timezone
│       ├── encryption.py          # Fernet-based TokenEncryption for OAuth tokens
│       ├── timeparse.py           # parse_hhmm() — parses "HH:MM" strings to time objects
│       ├── timezone_resolver.py   # City name → IANA timezone lookup (100+ cities)
│       └── validators.py          # is_valid_timezone(), clamp_age()
├── alembic/                    # Database migrations
│   ├── env.py                  # Alembic environment setup
│   ├── versions/               # Migration revision files
│   └── README
├── scripts/                    # Utility scripts (run outside Docker)
│   ├── generate_data_keyset.py     # Generate Tink AEAD keyset
│   ├── backfill_encrypted_columns.py  # Encrypt existing plaintext rows
│   ├── migrate_core_text_to_core_fact.py
│   ├── check_db_url.py
│   ├── enable_pgvector.sql
│   └── init_schema.sql
├── tests/
│   ├── conftest.py
│   ├── test_job_manager.py
│   ├── test_memory_orchestrator_and_core_memory.py
│   ├── test_scheduler_and_encryption.py
│   └── test_scheduler_reminder_tool.py
├── docker/
│   ├── app.Dockerfile          # Python 3.11-slim + ffmpeg + Poetry
│   └── sandbox.Dockerfile      # Python sandbox image with matplotlib/docx/xlsx/pptx
├── docker-compose.yml          # app, db (pgvector/pg16), redis, nginx-proxy-manager
├── pyproject.toml              # Poetry config + dev dependencies
├── alembic.ini                 # Alembic config (DB URL read from app.config.settings)
└── .env.example                # Environment variable template
```

---

## Key Architectural Patterns

### 1. Webhook-Based Telegram Bot

The app runs as a FastAPI server. Telegram sends updates via HTTP POST to `/telegram/webhook`. The webhook secret is validated on every request. FSM state is persisted in Redis so it survives restarts.

### 2. ReAct Tool-Calling Loop

`ConversationService.respond_with_tools()` implements a ReAct (Reason+Act) pattern:
1. Assemble system prompt (persona + user memory context + skills snippet)
2. Call LLM with `tools=ALL_TOOLS`, `tool_choice="auto"`
3. If the model returns tool calls, execute them via `ToolExecutor` and loop
4. Continue until no tool calls (final answer) or `max_iterations=5`

Tool definitions live in `app/llm/tool_schemas.py`. Tool execution logic lives in `app/services/tool_executor.py`.

**Available LLM Tools** (defined in `tool_schemas.py`):

| Tool | Description |
|---|---|
| `schedule_reminder` | Schedule a one-off reminder at a specific datetime |
| `cancel_reminder` | Cancel a scheduled reminder by job_id |
| `list_reminders` | List all active reminders for the user |
| `create_plan` | Create a daily/weekly/monthly plan |
| `check_plan` | Check active (non-expired) plans |
| `edit_plan` | Edit an existing plan's content or extend its expiry |
| `create_calendar_event` | Create a Google Calendar event |
| `check_calendar_availability` | Check if user is free during a time window |
| `execute_code` | Run code in a sandboxed Docker container |
| `load_skill` | Load specialist skill instructions (progressive loading) |
| `web_search` | Search the web via Tavily API |

### 3. Three-Layer Memory Architecture

Each user message triggers memory assembly via `MemoryOrchestrator.assemble()`:

- **Core Memory** (`CoreFact` rows): Permanent facts about the user. Retrieved semantically (cosine similarity on pgvector) — only top-K relevant facts are injected into context to avoid bloat.
- **Working Memory** (`WorkingMemory`): Short-term summaries that decay after `WORKING_MEMORY_LIFETIME_DAYS` days.
- **Episodic Memory** (`Episode` + `EpisodeEmbedding`): Past conversation episodes retrieved via RAG (pgvector IVFFlat index).

The assembled `MemoryPack` is serialized to a JSON context block injected into the system prompt. All four memory queries run in parallel via `asyncio.gather()`.

### 4. Field-Level Encryption

Sensitive database columns use custom SQLAlchemy `TypeDecorator` types:
- `EncryptedTextType(column_label)` — for text fields
- `EncryptedJSONType(column_label)` — for JSON fields

These transparently encrypt on write and decrypt on read using Google Tink AEAD (AES256-GCM). The `column_label` is used as Additional Authenticated Data (AAD) to bind ciphertext to its column. Legacy plaintext values are returned with a warning; use `scripts/backfill_encrypted_columns.py` to migrate them.

### 5. Proactive Scheduling

`JobManager.schedule_user_jobs()` registers per-user APScheduler cron jobs for:
- Morning check-in (at user's wake time)
- Evening wrap-up (1 hour before bed time)
- Weekly review (Sundays at 18:00 local)
- Monthly review (1st of month at 18:00 local)
- News digest (wake_time + `NEWS_DIGEST_OFFSET_MINUTES`, opt-in)

Additionally, `JobManager.schedule_user_triggers()` handles user-defined custom triggers.

Job IDs follow patterns like `{type}_{user_id}` (e.g., `morning_42`) or `trigger_{user_id}_{trigger_id}`.

### 6. Conversation History

Short-term conversation turns (user + assistant text only) are stored in Redis via `ConversationHistoryService`. System messages and raw tool call/result messages are excluded from storage — the system prompt is regenerated fresh each turn with current memory context.

### 7. Agent Skills (Progressive Loading)

Skills are `.md` files in `app/skills/` with YAML-like frontmatter:

```markdown
---
name: word-document
description: Create Word (.docx) documents...
---
# Full instructions here...
```

**Two-level loading:**
- **Level 1 (metadata)**: Name + description is appended to every system prompt (~80 tokens per skill). The LLM sees what's available.
- **Level 2 (full instructions)**: The LLM calls `load_skill(name)` to load the full instructions only when needed (300–1500 tokens).

Current skills: `cv-resume`, `data-analysis`, `excel-spreadsheet`, `powerpoint-presentation`, `project-planner`, `study-planner`, `word-document`.

### 8. Sandboxed Code Execution

The LLM can run code via the `execute_code` tool inside isolated Docker containers.

**Python sandbox image** (`motivi-sandbox:latest`, built from `docker/sandbox.Dockerfile`) includes: matplotlib, numpy, pandas, scipy, seaborn, python-docx, openpyxl, python-pptx, Pillow.

**Security controls (all enforced at the Docker level):**

| Control | Value |
|---|---|
| Network | `--network=none` (completely disabled) |
| Filesystem | `--read-only` root + `/tmp` tmpfs (32 MB) |
| Memory | `--memory=256m` (hard limit, swap disabled) |
| CPU | `--cpu-quota` = 0.5 cores |
| Process limit | `--pids-limit=64` (prevents fork bombs) |
| Linux capabilities | `--cap-drop=ALL` |
| Privilege escalation | `--security-opt=no-new-privileges` |
| User | `-u nobody` (non-root) |
| Wall-clock timeout | 30 seconds (container force-killed) |
| Output cap | 8 KB stdout/stderr |
| Container lifetime | `--rm` (auto-deleted after exit) |

**File output:** Python code can save files to `/output/` inside the container. After execution, files (up to 10 files, 10 MB each, 25 MB total) with allowed extensions are collected and sent to the user via Telegram (images as photos, everything else as documents).

**Supported languages:**

| Language key | Docker image |
|---|---|
| `python` / `python3` | `motivi-sandbox:latest` |
| `javascript` / `js` | `node:20-alpine` |
| `bash` / `sh` | `alpine:3` |

**Rate limiting:** Trial users get 5 executions/day, Premium gets 50. Expired users are blocked. Admins bypass limits.

### 9. Web Search (Tavily)

The `web_search` tool uses the Tavily API for real-time web and news search.

- Results are cached in Redis (TTL from `SEARCH_CACHE_TTL`, default 1 hour)
- Rate-limited per user per day (Trial: 10, Premium: 100, Admin: unlimited)
- Supports `general` and `news` search types

### 10. Personalised News Digest

`NewsDigestService` generates search queries from the user's occupation and core memory facts that mention interests/hobbies. Articles are fetched via `SearchService` (news type) and formatted as an XML block injected into the proactive flow prompt. Fires daily at wake_time + offset (default 30 min), opt-in via `enable_news_digest` setting.

### 11. Read-Only Telegram Userbot (MTProto)

Users can connect their personal Telegram account via `/connect_userbot`. The system uses Telethon (MTProto) to monitor:

- **Channel posts**: LLM classifies whether a post matches the user's interests. If yes, a notification with an excerpt and link is sent via the bot.
- **Incoming DMs**: LLM generates 3 reply suggestions. A notification with the suggestions is sent via the bot.

**Safety guarantees:**
- Strictly read-only: no write operations (no send_message, mark_as_read, etc.)
- Session strings encrypted at rest via `EncryptedTextType`
- Rate-limited: max N notifications per channel per user per day (configurable)
- Users can set interests via `/userbot_interests` and toggle features in settings

### 12. Custom User Triggers

Users can define their own recurring proactive prompts via `/add_trigger`:
- FSM-based creation flow (name → prompt → HH:MM time → weekday schedule)
- Supports Russian and English weekday names
- Max 5 triggers per user
- Each trigger fires an LLM-powered proactive flow at the scheduled time
- Managed via `/triggers` with inline keyboard (toggle on/off, delete)

### 13. Multi-Language Support

`ConversationService` loads both Russian (`moti_system.txt`) and English (`moti_system_eng.txt`) persona prompts. The `language` parameter (default `"ru"`) selects which prompt to use. The extractor prompt also has both language variants (`gemma_system.txt` / `gemma_system_eng.txt`).

### 14. Group Chat Support

The bot works inside Telegram groups and supergroups. It responds **only** when explicitly addressed:
- User sends a message containing `@botusername`
- User replies to one of the bot's own messages

All other group messages are silently ignored. The full per-user memory/subscription/history pipeline runs as normal — memories are stored under the user's personal profile.

---

## Router Registration Order

Registration order in `dispatcher.py` matters — earlier routers take priority:

1. `onboarding_router` — /start flow
2. `subscription_router` — /subscribe, payments
3. `oauth_router` — /connect_calendar
4. `habits_router` — /habits, /add_habit
5. `profile_router` — /profile
6. `settings_router` — /settings
7. `break_mode_router` — /break
8. `admin_router` — admin commands
9. `group_router` — group/supergroup messages
10. `triggers_router` — /triggers, /add_trigger
11. `userbot_router` — /connect_userbot, /disconnect_userbot, /userbot_interests
12. `multimodal_router` — voice notes, photos
13. `chat_router` — main natural language handler (catch-all)
14. `common_router` — fallback/unknown commands

---

## Configuration (app/config.py)

All configuration is loaded from environment variables via Pydantic Settings. Key settings:

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Telegram bot token |
| `TELEGRAM_WEBHOOK_SECRET` | Validates incoming webhook requests |
| `PUBLIC_BASE_URL` | Publicly accessible HTTPS URL for webhook |
| `DATABASE_URL` | PostgreSQL async URL (`postgresql+asyncpg://...`) |
| `REDIS_URL` | Redis connection URL |
| `OPENROUTER_API_KEY` | OpenRouter API key |
| `LLM_MODEL_ID` | Main conversational model |
| `AUDIO_IMAGE_MODEL_ID` | Audio/image model |
| `EMBEDDING_MODEL_ID` | Embedding model |
| `EXTRACTOR_MODEL_ID` | Fact extraction model |
| `ENCRYPTION_KEY` | Fernet key (32 url-safe base64 bytes) |
| `DATA_ENCRYPTION_KEYSET_B64` | Tink AEAD keyset (base64-encoded JSON) |
| `VECTOR_DIM` | Embedding dimensions (default: 4096) |
| `ADMIN_USER_IDS` | Comma-separated Telegram user IDs for admin commands |
| `ENV` | `dev` or `production` |
| `TRIAL_DAYS` | Days of free trial (default: 7) |
| `SUBSCRIPTION_PRICE_STARS` | Telegram Stars price for premium (default: 100) |
| `CODE_EXEC_DAILY_TRIAL` | Code exec limit for trial users (default: 5) |
| `CODE_EXEC_DAILY_PREMIUM` | Code exec limit for premium users (default: 50) |
| `TAVILY_API_KEY` | Tavily API key for web search |
| `SEARCH_CACHE_TTL` | Redis TTL for search cache (default: 3600s) |
| `SEARCH_MAX_RESULTS` | Max search results per call (default: 5) |
| `SEARCH_DAILY_TRIAL` | Daily search limit for trial (default: 10) |
| `SEARCH_DAILY_PREMIUM` | Daily search limit for premium (default: 100) |
| `NEWS_DIGEST_OFFSET_MINUTES` | Minutes after wake_time for news digest (default: 30) |
| `TELEGRAM_API_ID` | Telegram MTProto API ID (for userbot) |
| `TELEGRAM_API_HASH` | Telegram MTProto API hash (for userbot) |
| `USERBOT_MAX_CHANNEL_NOTIFS_PER_DAY` | Max channel notifications per user per day (default: 5) |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret |
| `GOOGLE_REDIRECT_URI` | Google OAuth redirect URI |
| `SENTRY_DSN` | Sentry DSN for error monitoring |

---

## Development Workflows

### Local Setup

```bash
# 1. Install dependencies
poetry install

# 2. Copy and configure environment
cp .env.example .env
# Edit .env with your API keys and tokens

# 3. Generate encryption keys
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
python scripts/generate_data_keyset.py

# 4. Start infrastructure (DB + Redis)
docker-compose up db redis -d

# 5. Apply DB migrations
poetry run alembic upgrade head

# 6. Build the Python sandbox image (for code execution)
docker build -f docker/sandbox.Dockerfile -t motivi-sandbox:latest .
docker pull node:20-alpine
docker pull alpine:3

# 7. Run the app (development)
ENV=dev poetry run uvicorn app.main:app --reload --port 8000
```

### Docker (Production)

```bash
docker-compose up --build -d
docker-compose exec app alembic upgrade head
```

### Database Migrations

```bash
# Create a new migration (after changing models)
poetry run alembic revision --autogenerate -m "description"

# Apply migrations
poetry run alembic upgrade head

# Rollback one step
poetry run alembic downgrade -1
```

**Important:** In `production` mode (`ENV=production`), `SQLModel.metadata.create_all` is NOT called — migrations are the only way to update the schema. In `dev` mode, tables are auto-created for convenience.

### Running Tests

```bash
poetry run pytest tests/ -v
```

Tests require a real database connection. Check `tests/conftest.py` for setup.

### Linting and Formatting

```bash
# Lint with ruff
poetry run ruff check app/

# Format with black
poetry run black app/

# Type checking
poetry run mypy app/
```

---

## Adding a New Bot Command / Feature

1. **Add a router** in `app/bot/routers/your_feature.py`. Use `Router(name="your_feature")`.
2. **Register the router** in `app/bot/dispatcher.py` via `dp.include_router(your_router)`. Mind the registration order — command routers go before `group_router`, `multimodal_router`, and `chat_router`.
3. **Add FSM states** (if multi-step) in `app/bot/states.py`.
4. **Create service** in `app/services/your_service.py` for business logic.
5. **Add models** in `app/models/your_model.py` and generate a migration.
6. **Expose to LLM** (optional): add a tool schema in `app/llm/tool_schemas.py` and executor in `app/services/tool_executor.py`.

## Adding a New LLM Tool

1. Define the tool schema in `app/llm/tool_schemas.py` following the existing `TOOL_*` pattern.
2. Add it to the `RAW_TOOLS` list at the bottom of that file (it auto-wraps into `ALL_TOOLS`).
3. Implement execution logic in `app/services/tool_executor.py` in the `execute()` dispatch method.

## Adding a New Agent Skill

1. Create a `.md` file in `app/skills/` with YAML frontmatter:
   ```markdown
   ---
   name: my-skill
   description: One-line description of what this skill does
   ---
   # Full step-by-step instructions here...
   ```
2. The skill is automatically discovered by `SkillsService` — no code changes needed.
3. The metadata cache is built once on first request. Restart the app after adding skills in production.

## Adding a New Encrypted Column

Use `EncryptedTextType` or `EncryptedJSONType` from `app/security/encrypted_types.py`:

```python
from ..security.encrypted_types import EncryptedTextType, EncryptedJSONType
from sqlalchemy import Column

class MyModel(SQLModel, table=True):
    sensitive_text: Optional[str] = Field(
        default=None,
        sa_column=Column(EncryptedTextType("mymodel.sensitive_text"), nullable=True),
    )
```

The `column_label` argument (e.g., `"mymodel.sensitive_text"`) must be unique per column — it is used as AAD and changing it will break decryption of existing rows.

---

## Key Conventions

### Code Style
- **Python 3.11+** features are available (e.g., `str | None` union types, `match` statements)
- Use `from __future__ import annotations` for forward references
- Async-first: all DB operations, LLM calls, and Telegram API calls use `async/await`
- Use `loguru` for logging (not the stdlib `logging` module): `from loguru import logger`
- Use loguru positional-arg format (`logger.info("msg {}", val)`) — NOT f-strings or `%s` format
- Pydantic v2 models throughout (including SQLModel)

### Database Sessions
- The `DBSessionMiddleware` injects a session as `session` into handler keyword arguments
- In service-layer code called from outside handlers, use the `get_session()` async context manager from `app/db.py`
- Sessions auto-commit on success and auto-rollback on exception

### Error Handling
- Log exceptions with `logger.exception()` (includes traceback)
- Show user-friendly messages — never expose raw exception text to Telegram users
- The main chat handler sends a "thinking..." message immediately, then replaces it with the response

### Telegram Message Formatting
- Bot is configured with `parse_mode="HTML"` by default
- Use HTML tags (`<b>`, `<i>`, `<code>`, etc.) in response text — not Markdown
- Escape user-generated content with `html.escape()` before embedding in HTML

### Timezone Handling
- User timezones are stored as IANA timezone strings (e.g., `"Europe/Moscow"`)
- All `datetime` objects stored in the DB should be timezone-aware UTC
- Use `ZoneInfo` (stdlib) not `pytz` for new timezone operations, though both exist in the codebase
- `app/utils/timezone_resolver.py` maps 100+ city names to IANA timezones

### Subscription Tiers
Three user states:
- **Trial**: First 7 days after account creation (`user.is_trial == True`)
- **Premium**: Active subscription (`user.is_premium == True`)
- **Expired**: Trial over, no subscription (hard-blocked from AI responses)

Daily message quotas: Trial=20, Premium=200, Expired=0 (configurable in `config.py`).

Code execution and web search are also gated by subscription tier with separate daily limits.

### Rate Limiting Pattern
The codebase uses a consistent Redis-based daily counter pattern for rate limiting:
- Key format: `{feature}:{user_id}:{YYYY-MM-DD}`
- `INCR` the key, set `EXPIRE` on first increment (86400 + 3600 buffer)
- Used for: code execution, web search, userbot channel notifications

---

## Environment Differences

| | `ENV=dev` | `ENV=production` |
|---|---|---|
| DB table creation | `SQLModel.metadata.create_all` on startup | Migrations only |
| Logging | Configurable via `LOG_LEVEL` | Same |
| Metrics endpoint | Available if `ENABLE_METRICS=true` | Same |

---

## Important Files to Know

| File | Purpose |
|---|---|
| `app/main.py` | Application entry point, all HTTP routes, lifespan (startup/shutdown) |
| `app/config.py` | Single source of truth for all configuration |
| `app/bot/dispatcher.py` | Router/middleware registration order matters |
| `app/bot/states.py` | All FSM state groups (Onboarding, HabitCreation, TriggerCreation, UserBotSetup) |
| `app/llm/conversation_service.py` | Core LLM interaction logic (ReAct loop) |
| `app/llm/tool_schemas.py` | All tools available to the LLM (11 tools) |
| `app/services/memory_orchestrator.py` | Memory assembly (central to every conversation) |
| `app/services/tool_executor.py` | Tool call dispatch (all 11 handlers) |
| `app/services/code_executor_service.py` | Sandboxed Docker code execution |
| `app/services/skills_service.py` | Agent Skills progressive loading |
| `app/services/search_service.py` | Tavily web search with caching |
| `app/services/news_digest_service.py` | Personalised news digest |
| `app/services/userbot_manager.py` | Telethon client lifecycle |
| `app/services/userbot_monitor.py` | Channel/DM event handlers with LLM classification |
| `app/prompts/moti_system.txt` | Bot personality and instructions (Russian) |
| `app/prompts/moti_system_eng.txt` | Bot personality and instructions (English) |
| `app/security/encrypted_types.py` | Column encryption TypeDecorators |
| `app/scheduler/job_manager.py` | Proactive scheduling + custom triggers |
| `app/scheduler/jobs.py` | All job functions (proactive flows, triggers, reminders, cleanup) |
| `app/skills/*.md` | Agent Skill instruction files (7 skills) |
| `alembic/versions/` | All DB migration history |

---

## Alembic Migration History

| Migration | Description |
|---|---|
| `803a95fd0d9e` | Initial structure |
| `16c8dbaee964` | Add created_at fields to core memory |
| `8edfc37203e1` | Add plans table |
| `962e790beaf7` | Add subscription fields |
| `fc08a8eb9107` | Add core_fact and core_fact_emb |
| `20251204` | Add CoreFact table |
| `20251212` | Vector 4096 dimensions |
| `20260128` | Add vector indexes |
| `20260226` | Add user_triggers table |
| `20260228` | Add search/news digest settings |
| `20260301` | Add userbot_session and settings |
| `51d1ea426c9b` | Merge heads |

---

## Dependencies (pyproject.toml)

Key production dependencies beyond the standard web/DB stack:

| Package | Purpose |
|---|---|
| `telethon` | MTProto client for Telegram userbot |
| `httpx` | Async HTTP client (used by SearchService for Tavily API) |
| `tink` | Google Tink AEAD encryption |
| `cryptography` | Fernet encryption for OAuth tokens |
| `faster-whisper` | Speech-to-text |
| `python-docx` | Word document generation (also in sandbox) |
| `pillow` | Image processing |
| `ffmpeg-python` + `av` | Audio/video processing |
| `pgvector` | PostgreSQL vector similarity search |
| `apscheduler` | Cron-style job scheduling |
| `redis` | Session storage, caching, rate limiting |

---

## Future Feature Roadmap

### Near-term

| Feature | Description | Key files to touch |
|---|---|---|
| **Alembic migration for group chats** | Add `group_id` column to conversation history (for per-group context isolation) | `app/models/`, `alembic/versions/` |
| **File/image output from code exec** | Extend JS/bash sandbox to support file output | `app/services/code_executor_service.py` |

### Medium-term

| Feature | Description |
|---|---|
| **Web dashboard** | React/Next.js read-only dashboard showing habits, streaks, memory stats; protected by Telegram Login Widget |
| **Notion / Obsidian export** | Export core memory, habits, and episodes to Markdown or Notion pages via API |
| **Per-group personality** | Group admins can configure a group-specific system prompt addon (e.g., team stand-up facilitator mode) |
| **Shared group habits** | Habit challenges that multiple group members can join and track together |

### Long-term / Architectural

| Feature | Description |
|---|---|
| **Streaming LLM responses** | Use SSE / chunked Telegram `sendChatAction` + message edits for real-time response feel |
| **Voice response** | TTS output (ElevenLabs or OpenRouter audio) for voice note replies |
| **Vector DB upgrade** | Replace pgvector IVFFlat with HNSW index or dedicated Qdrant service when user count exceeds ~10k |
| **Multi-tenant SaaS** | Tenant isolation at DB level for white-label deployments |
| **MCP server integration** | Expose bot tools as an MCP server so other AI systems can call into Motivi's memory and scheduling |


# Claude / AI Senior Engineer Prompt (Plan Mode)

Before writing any code, review the plan thoroughly.  
Do NOT start implementation until the review is complete and I approve the direction.

For every issue or recommendation:
- Explain the concrete tradeoffs
- Give an opinionated recommendation
- Ask for my input before proceeding

Engineering principles to follow:
- Prefer DRY — aggressively flag duplication
- Well-tested code is mandatory (better too many tests than too few)
- Code should be “engineered enough” — not fragile or hacky, but not over-engineered
- Optimize for correctness and edge cases over speed of implementation
- Prefer explicit solutions over clever ones

---

## 1. Architecture Review

Evaluate:
- Overall system design and component boundaries
- Dependency graph and coupling risks
- Data flow and potential bottlenecks
- Scaling characteristics and single points of failure
- Security boundaries (auth, data access, API limits)

---

## 2. Code Quality Review

Evaluate:
- Project structure and module organization
- DRY violations
- Error handling patterns and missing edge cases
- Technical debt risks
- Areas that are over-engineered or under-engineered

---

## 3. Test Review

Evaluate:
- Test coverage (unit, integration, e2e)
- Quality of assertions
- Missing edge cases
- Failure scenarios that are not tested

---

## 4. Performance Review

Evaluate:
- N+1 queries or inefficient I/O
- Memory usage risks
- CPU hotspots or heavy code paths
- Caching opportunities
- Latency and scalability concerns

---

## For each issue found:

Provide:
1. Clear description of the problem
2. Why it matters
3. 2–3 options (including “do nothing” if reasonable)
4. For each option:
   - Effort
   - Risk
   - Impact
   - Maintenance cost
5. Your recommended option and why

Then ask for approval before moving forward.

---

## Workflow Rules

- Do NOT assume priorities or timelines
- After each section (Architecture → Code → Tests → Performance), pause and ask for feedback
- Do NOT implement anything until I confirm

---

## Start Mode

Before starting, ask:

**Is this a BIG change or a SMALL change?**

BIG change:
- Review all sections step-by-step
- Highlight the top 3–4 issues per section

SMALL change:
- Ask one focused question per section
- Keep the review concise

---

## Output Style

- Structured and concise
- Opinionated recommendations (not neutral summaries)
- Focus on real risks and tradeoffs
- Think and act like a Staff/Senior Engineer reviewing a production system