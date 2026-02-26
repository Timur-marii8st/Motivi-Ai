# CLAUDE.md — Motivi_AI Codebase Guide

This file provides context for AI assistants working on this codebase.

## Project Overview

**Motivi_AI** is a proactive Telegram planning assistant powered by LLMs. It uses a cognitive memory architecture (Core, Working, and Episodic memory) with RAG-based retrieval, habit tracking, Google Calendar integration, and autonomous scheduled interactions (morning/evening check-ins, weekly reviews).

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
│   │   │   ├── habits.py       # /habits, /add_habit
│   │   │   ├── profile.py      # /profile, account deletion
│   │   │   ├── settings.py     # /settings (toggle proactive flows, break mode)
│   │   │   ├── subscription.py # /subscribe, Telegram Stars payments
│   │   │   ├── oauth.py        # /connect_calendar
│   │   │   ├── multimodal.py   # Voice notes + photo handling
│   │   │   ├── admin.py        # Admin-only commands
│   │   │   ├── break_mode.py   # /break command
│   │   │   └── common.py       # Fallback / unknown command handler
│   │   ├── middlewares/
│   │   │   └── db_session.py   # Injects async DB session into handler data
│   │   ├── init.py             # Bot command registration
│   │   └── states.py           # Aiogram FSM state groups
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
│   │   ├── proactive_flows.py          # Morning/Evening/Weekly/Monthly check-in orchestration
│   │   ├── profile_services.py         # get_or_create_user, profile updates
│   │   ├── account_service.py          # Account deletion (GDPR)
│   │   ├── oauth_state_service.py      # OAuth state token management (Redis)
│   │   ├── settings_service.py         # UserSettings CRUD
│   │   ├── stt_service.py              # Speech-to-text (Whisper via faster-whisper)
│   │   ├── vision_service.py           # Image analysis
│   │   ├── subscription_service.py     # Telegram Stars subscription logic
│   │   └── profile_completeness_service.py  # Tracks user question/interaction counts
│   ├── models/                 # SQLModel table definitions
│   │   ├── users.py            # User (main table, encrypted name/occupation)
│   │   ├── core_memory.py      # CoreMemory + CoreFact (with vector embedding)
│   │   ├── working_memory.py   # WorkingMemory + WorkingMemoryEntry
│   │   ├── episode.py          # Episode + EpisodeEmbedding (pgvector)
│   │   ├── habit.py            # Habit + HabitLog
│   │   ├── settings.py         # UserSettings (proactive flow toggles)
│   │   ├── oauth_token.py      # Google OAuth credentials (encrypted)
│   │   ├── plan.py             # Plan (daily/weekly/monthly, time-expiring)
│   │   ├── facts.py            # CoreFact model
│   │   └── profile_completeness.py  # ProfileCompleteness tracking
│   ├── scheduler/
│   │   ├── scheduler_instance.py  # APScheduler singleton
│   │   ├── job_manager.py         # Per-user job scheduling (morning/evening/weekly/monthly)
│   │   ├── jobs.py                # Job functions called by APScheduler
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
│       └── get_user_time.py       # Helper: current time in user's timezone
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
│   └── app.Dockerfile          # Python 3.11-slim + ffmpeg + Poetry
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
1. Assemble system prompt (persona + user memory context)
2. Call LLM with `tools=ALL_TOOLS`, `tool_choice="auto"`
3. If the model returns tool calls, execute them via `ToolExecutor` and loop
4. Continue until no tool calls (final answer) or `max_iterations=5`

Tool definitions live in `app/llm/tool_schemas.py`. Tool execution logic lives in `app/services/tool_executor.py`.

### 3. Three-Layer Memory Architecture

Each user message triggers memory assembly via `MemoryOrchestrator.assemble()`:

- **Core Memory** (`CoreFact` rows): Permanent facts about the user. Retrieved semantically (cosine similarity on pgvector) — only top-K relevant facts are injected into context to avoid bloat.
- **Working Memory** (`WorkingMemory`): Short-term summaries that decay after `WORKING_MEMORY_LIFETIME_DAYS` days.
- **Episodic Memory** (`Episode` + `EpisodeEmbedding`): Past conversation episodes retrieved via RAG (pgvector IVFFlat index).

The assembled `MemoryPack` is serialized to a JSON context block injected into the system prompt.

### 4. Field-Level Encryption

Sensitive database columns use custom SQLAlchemy `TypeDecorator` types:
- `EncryptedTextType(column_label)` — for text fields
- `EncryptedJSONType(column_label)` — for JSON fields

These transparently encrypt on write and decrypt on read using Google Tink AEAD (AES256-GCM). The `column_label` is used as Additional Authenticated Data (AAD) to bind ciphertext to its column. Legacy plaintext values are returned with a warning; use `scripts/backfill_encrypted_columns.py` to migrate them.

### 5. Proactive Scheduling

`JobManager.schedule_user_jobs()` registers per-user APScheduler cron jobs for:
- Morning check-in (at user's wake time)
- Evening wrap-up (1 hour before bed time)
- Weekly review (configurable)
- Monthly review (configurable)

Job IDs follow the pattern `{type}_{user_id}` (e.g., `morning_42`). Jobs are replaced atomically when settings change.

### 6. Conversation History

Short-term conversation turns (user + assistant text only) are stored in Redis via `ConversationHistoryService`. System messages and raw tool call/result messages are excluded from storage — the system prompt is regenerated fresh each turn with current memory context.

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
| `LLM_MODEL_ID` | Main conversational model (default: `x-ai/grok-4.1-fast`) |
| `AUDIO_IMAGE_MODEL_ID` | Audio/image model (default: `google/gemini-2.0-flash-lite-001`) |
| `EMBEDDING_MODEL_ID` | Embedding model (default: `qwen/qwen3-embedding-8b`) |
| `EXTRACTOR_MODEL_ID` | Fact extraction model (default: `google/gemma-3n-e4b-it`) |
| `ENCRYPTION_KEY` | Fernet key (32 url-safe base64 bytes) |
| `DATA_ENCRYPTION_KEYSET_B64` | Tink AEAD keyset (base64-encoded JSON) |
| `VECTOR_DIM` | Embedding dimensions (default: 4096 for Qwen3-8b) |
| `ADMIN_USER_IDS` | Comma-separated Telegram user IDs for admin commands |
| `ENV` | `dev` or `production` (dev skips migrations, uses `create_all`) |
| `TRIAL_DAYS` | Days of free trial (default: 7) |
| `SUBSCRIPTION_PRICE_STARS` | Telegram Stars price for premium (default: 100) |

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

# 6. Run the app (development)
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
2. **Register the router** in `app/bot/dispatcher.py` via `dp.include_router(your_router)`.
3. **Add FSM states** (if multi-step) in `app/bot/states.py`.
4. **Create service** in `app/services/your_service.py` for business logic.
5. **Add models** in `app/models/your_model.py` and generate a migration.
6. **Expose to LLM** (optional): add a tool schema in `app/llm/tool_schemas.py` and executor in `app/services/tool_executor.py`.

## Adding a New LLM Tool

1. Define the tool schema in `app/llm/tool_schemas.py` following the existing `TOOL_*` pattern.
2. Add it to the `ALL_TOOLS` list at the bottom of that file.
3. Implement execution logic in `app/services/tool_executor.py` in the `execute()` dispatch method.

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

### Timezone Handling
- User timezones are stored as IANA timezone strings (e.g., `"Europe/Moscow"`)
- All `datetime` objects stored in the DB should be timezone-aware UTC
- Use `ZoneInfo` (stdlib) not `pytz` for new timezone operations, though both exist in the codebase

### Subscription Tiers
Three user states:
- **Trial**: First 7 days after account creation (`user.is_trial == True`)
- **Premium**: Active subscription (`user.is_premium == True`)
- **Expired**: Trial over, no subscription (hard-blocked from AI responses)

Daily message quotas: Trial=20, Premium=200, Expired=0 (configurable in `config.py`).

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
| `app/main.py` | Application entry point, all HTTP routes |
| `app/config.py` | Single source of truth for all configuration |
| `app/bot/dispatcher.py` | Router/middleware registration order matters |
| `app/llm/conversation_service.py` | Core LLM interaction logic |
| `app/llm/tool_schemas.py` | All tools available to the LLM |
| `app/services/memory_orchestrator.py` | Memory assembly (central to every conversation) |
| `app/services/tool_executor.py` | Tool call dispatch |
| `app/prompts/moti_system.txt` | Bot personality and instructions (Russian) |
| `app/security/encrypted_types.py` | Column encryption TypeDecorators |
| `app/scheduler/job_manager.py` | Proactive scheduling logic |
| `alembic/versions/` | All DB migration history |
