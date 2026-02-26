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

---

## Recent Changes (2026-02-26)

### Bug Fixes & Optimisations Applied

| File | Fix |
|---|---|
| `app/models/users.py` | Removed duplicate `touch()` method definition (was defined twice) |
| `app/services/extractor_service.py` | Replaced stdlib `logging` with `loguru`; fixed f-string → loguru positional-arg format |
| `app/services/proactive_flows.py` | Extracted 4-method duplication into single `_run_flow()` helper; shared `GeminiEmbeddings` singleton across instances; parallelised history save + bot.send with `asyncio.gather` |
| `app/scheduler/jobs.py` | Removed duplicate imports (`datetime`, `timedelta`, `delete`); extracted 4 identical job functions into `_run_proactive_job()`; wrapped `bot.send_message` in `try/finally` to guarantee `bot.session.close()` on exception |
| `app/bot/routers/habits.py` | Fixed `user.timezone` → `user.user_timezone` (wrong property name caused AttributeError); moved `Habit` import to top of file; added `timezone.utc` fallback when user has no timezone set; fixed `%s` logger format → loguru `{}` |
| `app/bot/routers/chat.py` | Fixed `%s` logger format → loguru `{}` in exception handlers |
| `app/services/memory_orchestrator.py` | Parallelised all four independent DB/vector queries using `asyncio.gather()` — reduces memory assembly latency by ~3× under load; fixed `Optional[List]` type hint → `Optional[List[Any]]` |

### New Features Added

#### 1. Group Chat Support (`app/bot/routers/group.py`)

The bot now works inside Telegram groups and supergroups. It responds **only** when explicitly addressed:

- User sends a message that contains `@botusername`
- User replies to one of the bot's own messages

All other group messages are silently ignored (no eavesdropping). The full per-user memory/subscription/history pipeline runs as normal — memories are stored under the user's personal profile (DM-first approach).

**Router registration:** `group_router` is registered in `dispatcher.py` before `multimodal_router` and `chat_router` but after all command routers, so commands still take priority.

**Key functions in `group.py`:**
- `_is_group_message(message)` — filter: only fires on group/supergroup chats
- `_bot_is_mentioned(message, bot)` — checks reply-to-bot and @mention
- `_strip_bot_mention(text, bot_username)` — removes @mention noise before LLM sees the text

#### 2. Sandboxed Code Execution (`app/services/code_executor_service.py`)

The LLM can now run code on behalf of users inside an isolated Docker container. This is exposed as the `execute_code` LLM tool (see `tool_schemas.py` and `tool_executor.py`).

**Safety measures (all enforced at the Docker level):**

| Control | Value |
|---|---|
| Network | `--network=none` (completely disabled) |
| Filesystem | `--read-only` root + small `/tmp` tmpfs |
| Memory | `--memory=128m` (hard limit, swap disabled) |
| CPU | `--cpu-quota` = 0.5 cores |
| Process limit | `--pids-limit=64` (prevents fork bombs) |
| Linux capabilities | `--cap-drop=ALL` |
| Privilege escalation | `--security-opt=no-new-privileges` |
| User | `-u nobody` (non-root) |
| Wall-clock timeout | 10 seconds (container force-killed) |
| Output cap | 8 KB |
| Container lifetime | `--rm` (auto-deleted after exit) |

**Supported languages:**

| Language key | Docker image |
|---|---|
| `python` / `python3` | `python:3.11-alpine` |
| `javascript` / `js` | `node:20-alpine` |
| `bash` / `sh` | `alpine:3` |

**Pre-pull images on the host** for fast cold starts:
```bash
docker pull python:3.11-alpine
docker pull node:20-alpine
docker pull alpine:3
```

**Configuration:** Timeout, memory, and CPU limits are hardcoded as constants in `code_executor_service.py`; move to `config.py` if you need env-based tunability.

---

## Future Feature Roadmap

### Near-term (next sprint)

| Feature | Description | Key files to touch |
|---|---|---|
| **Alembic migration for group chats** | Add `group_id` column to conversation history (optional, for per-group context isolation) | `app/models/`, `alembic/versions/` |
| **Code execution rate-limiting** | Prevent users from spamming the sandbox; count executions per user per day in Redis | `app/middleware/rate_limit.py`, `code_executor_service.py` |
| **Subscription gate for code exec** | Only Trial/Premium users can run code; expired users see upsell | `app/services/code_executor_service.py`, `tool_executor.py` |
| **Inline keyboard for habit logging** | Replace `/log_habit <id>` text command with buttons in `/habits` response | `app/bot/routers/habits.py` |
| **File/image output from code exec** | Allow matplotlib/PIL to save plots and send them as Telegram photos | `app/services/code_executor_service.py`, `app/bot/routers/group.py` |

### Medium-term

| Feature | Description |
|---|---|
| **Web dashboard** | React/Next.js read-only dashboard showing habits, streaks, memory stats; protected by Telegram Login Widget |
| **Notion / Obsidian export** | Export core memory, habits, and episodes to Markdown or Notion pages via API |
| **Custom proactive flow triggers** | Let users define their own recurring prompts (e.g., "every Friday at 17:00 ask me about my week") |
| **Multi-language bot** | Auto-detect user language from onboarding and load `moti_system_eng.txt` or `moti_system.txt` accordingly |
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
