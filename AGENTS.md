# AGENTS.md - Motivi_AI Codebase Guide

This file is the working guide for AI coding agents in this repository. It should track the current codebase, not the original product plan.

## Project Overview

**Motivi_AI** is a proactive Telegram planning assistant powered by LLMs. It combines long-term user memory, habit tracking, proactive planning, Google Calendar integration, sandboxed code execution, web search, agent skills, Telegram Stars subscriptions, gamification, and a Telethon-based userbot for read-only account monitoring plus opt-in reply approval.

The app is written in **Python 3.11**. Telegram updates are handled by **Aiogram 3.x** inside a **FastAPI** app. LLM calls go through **OpenRouter** with the OpenAI-compatible Python client.

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11 |
| Telegram framework | Aiogram 3.x |
| Web server | FastAPI + Uvicorn |
| Database | PostgreSQL 16 + pgvector |
| ORM | SQLModel + SQLAlchemy 2.x async |
| DB driver | asyncpg |
| LLM API | OpenRouter via `openai.AsyncOpenAI` |
| Embeddings | OpenRouter embedding API through `GeminiEmbeddings` |
| Web search | Tavily API via `SearchService` |
| MTProto | Telethon |
| Scheduling | APScheduler 3.x AsyncIO + SQLAlchemy job store |
| State/history cache | Redis |
| Encryption | Google Tink AEAD + Fernet |
| Dependency management | Poetry |
| Lint/format/typecheck | Ruff, Black, mypy |
| Tests | pytest |

## Repository Map

```text
app/
  main.py                         FastAPI app, lifespan, webhook/polling startup, health/metrics, OAuth callback
  config.py                       Pydantic settings and feature flag parsing
  db.py                           async engine/session, pgvector setup, row-integrity hook registration
  bot/
    dispatcher.py                 Bot/Dispatcher factory, Redis FSM storage, middleware, router order
    bot_provider.py               Global bot instance used by scheduler jobs
    middlewares/db_session.py     Per-update DB session lifecycle and private-topic tracking
    routers/                      Aiogram routers by feature domain
    states.py                     FSM states
  llm/
    client.py                     OpenRouter AsyncOpenAI singleton
    conversation_service.py       Persona prompt + memory + ReAct tool loop
    tool_schemas.py               OpenAI function-calling schemas
    gemini_client.py              Secondary model client for vision/audio/structured parsing
  services/
    memory_orchestrator.py        Core + Working + Episodic memory assembly
    core_memory_service.py        CoreFact storage/retrieval
    episodic_memory_service.py    Episodes and vector retrieval
    working_memory_service.py     Working memory with decay
    extractor_service.py          LLM-based memory extraction
    fact_cleanup_service.py       Core fact deduplication
    tool_executor.py              Implementation of all LLM tools
    conversation_history_service.py Redis-backed short chat history
    proactive_planning_service.py Smart LLM planner for one-off proactive touches
    proactive_flows.py            LLM proactive message generation
    userbot_manager.py            Telethon lifecycle
    userbot_monitor.py            Channel/DM/group event handlers
    userbot_thread_service.py     Persistent reply/follow-up tracking and memory ingest
    subscription_service.py       Trial/premium/admin status and payment validation
    event_bus.py                  Feature-flagged async domain event bus
    analytics_service.py          Gamification event persistence
    gamification/                 XP, badges, rewards, leaderboard listeners and schemas
    persona_service.py            Premium persona preference prompt modifier
  models/
    users.py                      User profile, subscription, streak/referral fields, private topic id
    settings.py                   User settings, smart proactivity, userbot, persona, gamification toggles
    payment.py                    Telegram Stars payment audit rows
    gamification.py               XP/badges/events/rewards/quests/pacts/circles
    userbot_thread.py             Persistent userbot message/follow-up state
    userbot_session.py            Encrypted Telethon session
    core_memory.py, facts.py      Core memory and facts
    working_memory.py             Working memory and embeddings
    episode.py                    Episodes and embeddings
    habit.py                      Habits and logs
    plan.py                       Daily/weekly/monthly plans
    user_trigger.py               Custom recurring triggers
  scheduler/
    scheduler_instance.py         APScheduler singleton and global jobs
    job_manager.py                Per-user jobs, triggers, smart planner, follow-up checks
    jobs.py                       Job functions
  prompts/
    personas/*.txt                Persona-specific system prompts, ru/en
    moti_system*.txt              Legacy fallback prompts
    gemma_system*.txt             Extractor prompts
  security/
    encrypted_types.py            Encrypted SQLAlchemy TypeDecorators
    encryption_manager.py         Tink AEAD singleton
    row_integrity.py              HMAC row integrity signatures
  skills/*.md                     Runtime agent skills exposed to the LLM
alembic/versions/                 Migration history
docs/                             Architecture, infra, vector dimension notes
scripts/                          Key generation, backfills, DB helpers
tests/                            pytest suite
docker/                           App and sandbox Dockerfiles
singbox/                          Telegram proxy example config
```

## Application Startup

`app/main.py` creates the bot/dispatcher at import time and stores the bot in `bot_provider`.

During lifespan startup:

1. Configure loguru.
2. Run `init_db()`; in `ENV=dev` it also calls `SQLModel.metadata.create_all`, while production relies on Alembic.
3. Start APScheduler.
4. Reschedule all user jobs with `JobManager.reschedule_all_user_jobs()`.
5. Register the analytics sink and import gamification listener modules.
6. Start all connected Telethon userbot clients.
7. Use polling when `TELEGRAM_USE_POLLING=true`; otherwise set the Telegram webhook to `{PUBLIC_BASE_URL}/telegram/webhook`.

Webhook requests validate `X-Telegram-Bot-Api-Secret-Token`. The webhook handler creates a background task for `dp.feed_update()` and returns immediately.

## Router Registration Order

Registration order in `app/bot/dispatcher.py` is significant:

1. `onboarding_router`
2. `subscription_router`
3. `oauth_router`
4. `habits_router`
5. `profile_router`
6. `settings_router`
7. `break_mode_router`
8. `admin_router`
9. `group_router`
10. `triggers_router`
11. `userbot_router`
12. `persona_router`
13. `gamification_router`
14. `referral_router`
15. `story_router`
16. `memories_router`
17. `multimodal_router`
18. `chat_router`
19. `common_router`

Keep command/state routers before catch-all natural chat and fallback routers.

Current user-facing router commands include:

| Router | Main commands/features |
|---|---|
| `onboarding.py` | `/start`, referral deep links, onboarding FSM |
| `subscription.py` | `/subscribe`, Telegram Stars pre-checkout and successful payment |
| `oauth.py` | `/connect_calendar` |
| `habits.py` | `/habits`, `/add_habit`, `/log_habit <id>` |
| `profile.py` | `/profile`, profile editing, account deletion |
| `settings.py` | `/settings`, smart proactivity, userbot, persona/gamification settings |
| `break_mode.py` | `/break`, `/export_data` |
| `admin.py` | `/admin_stats`, `/admin_broadcast` |
| `group.py` | group/supergroup mention/reply handling |
| `triggers.py` | `/triggers`, `/add_trigger` |
| `userbot.py` | `/connect_userbot`, `/disconnect_userbot`, `/userbot_interests`, `/userbot_pending`, reply approval/edit/dismiss callbacks |
| `persona.py` | `/persona` |
| `gamification.py` | `/level`, `/badges`, `/leaderboard` |
| `referral.py` | `/referral` |
| `story.py` | `/story` |
| `memories.py` | `/my_memories`, `/correct`, fact delete callbacks |
| `multimodal.py` | voice notes and photos |
| `chat.py` | natural text messages, explicit search prefixes |
| `common.py` | `/help`, fallback |

## Core Patterns

### LLM Conversation Loop

`ConversationService.respond_with_tools()` builds a fresh system message every turn:

- persona prompt from `app/prompts/personas/{strict|friendly|coach|zen|hype}_{ru|en}.txt`
- memory JSON from `MemoryPack.to_context_dict()`
- available skills metadata from `SkillsService`

It then runs a ReAct loop with `ALL_TOOLS`, executing tool calls through `ToolExecutor` until the model returns a final answer or `max_iterations` is reached.

Conversation history is Redis-backed and stores only user/assistant text turns. System messages and tool messages are intentionally excluded.

### Memory

The active memory stack is:

- Core memory: durable user facts, retrieved semantically.
- Working memory: short-term summaries with decay.
- Episodic memory: past conversation episodes and embeddings.

`MemoryOrchestrator.assemble()` gathers the relevant context for each user message. After chat responses, `ExtractorService` extracts important information, `FactCleanupService` deduplicates core facts, and scheduled jobs archive raw Redis conversation history into episodes.

### Personas and Language

The default persona id is `strict`. Supported ids are `strict`, `friendly`, `coach`, `zen`, and `hype`. Language is currently stored in `UserSettings.summary_preferences_json["language"]` and defaults to Russian unless Telegram locale starts with `en`.

The legacy `moti_system.txt` and `moti_system_eng.txt` files are fallbacks when persona files are missing.

### LLM Tools

Tool schemas live in `app/llm/tool_schemas.py`. Execution lives in `app/services/tool_executor.py`.

| Tool | Purpose |
|---|---|
| `schedule_reminder` | Schedule one-off Telegram reminder |
| `cancel_reminder` | Cancel reminder by job id |
| `list_reminders` | List active reminder jobs |
| `create_plan` | Store and send daily/weekly/monthly plan |
| `check_plan` | Return active non-expired plans |
| `edit_plan` | Update a plan and optionally extend expiry |
| `create_calendar_event` | Create Google Calendar event |
| `check_calendar_availability` | Check calendar free/busy |
| `execute_code` | Run code in sandbox and send output files |
| `load_skill` | Load full skill instructions |
| `web_search` | Tavily web/news search |

`chat.py` recognizes explicit search prefixes `!!`, `!search`, and `!поиск`; these force the first model action to `web_search`.

### Agent Skills

Skills are Markdown files in `app/skills/` with frontmatter:

```markdown
---
name: word-document
description: Create Word (.docx) documents...
---
Full instructions go here.
```

Only metadata is injected into the default system prompt. The model must call `load_skill(name)` before skill-specific tasks such as Word, Excel, PowerPoint, CV, study/project plans, or data analysis.

Current skills:

- `cv-resume`
- `data-analysis`
- `excel-spreadsheet`
- `powerpoint-presentation`
- `project-planner`
- `study-planner`
- `word-document`

### Sandboxed Code Execution

`CodeExecutorService` runs code in isolated Docker containers. Python uses `motivi-sandbox:latest`; JavaScript uses `node:20-alpine`; shell uses `alpine:3`.

Sandbox controls include no network, read-only root filesystem, `/tmp` tmpfs, memory/CPU/pid limits, dropped Linux capabilities, non-root user, timeout, and output caps. Python output files saved to `/output/` are collected and sent via Telegram as photos/documents.

Code execution is subscription-gated and rate-limited:

- Trial: `CODE_EXEC_DAILY_TRIAL`
- Premium: `CODE_EXEC_DAILY_PREMIUM`
- Admin: bypass
- Expired: blocked

### Web Search

`SearchService` calls Tavily and caches results in Redis for `SEARCH_CACHE_TTL`. It supports `general` and `news`. Search is subscription-gated and rate-limited with `SEARCH_DAILY_TRIAL` and `SEARCH_DAILY_PREMIUM`; admins bypass limits.

### Scheduling and Proactivity

APScheduler uses a SQLAlchemy job store backed by PostgreSQL. The scheduler singleton is in `app/scheduler/scheduler_instance.py`.

Global jobs currently include:

- `cleanup_expired_memories` at 03:00 UTC
- `archive_conversations` at 03:30 UTC
- `userbot_followup_check` every `USERBOT_FOLLOWUP_CHECK_INTERVAL_MINUTES`

Per-user scheduling is managed by `JobManager`:

- `proactive_planner_{user_id}`: daily smart planner near wake time
- `proactive_touch_{user_id}_...`: one-off messages scheduled by the planner
- `news_digest_{user_id}`: opt-in digest after wake time offset
- `channel_batch_{user_id}`: batched medium-priority userbot channel posts
- `trigger_{user_id}_{trigger_id}`: custom user triggers
- `habit_reminder_{habit_id}`: habit reminders

The old fixed morning/evening/weekly/monthly jobs are deprecated and route to the smart planner for compatibility.

Break mode is checked before proactive jobs, triggers, reminders, and most background user-facing sends.

### Smart Proactivity

`UserSettings.enable_smart_proactivity` controls whether the daily planner runs. `proactive_max_messages_per_day` limits planner-created touches. The planner asks the LLM whether a message is useful today/tomorrow and schedules concrete one-off `proactive_touch_job` jobs. After meaningful chat interactions, `JobManager.schedule_planner_refresh()` can schedule a near-future planner refresh.

### Telegram Userbot

Users connect personal Telegram accounts through `/connect_userbot`. Telethon sessions are encrypted in `UserBotSession`.

The userbot subsystem supports:

- Channel post relevance scoring with high-priority immediate notifications.
- Medium-priority channel batching and scheduled flushes.
- DM/group incoming message reply suggestions.
- Approval buttons, manual edit, dismiss, and pending thread listing.
- Persistent `UserBotThread` rows for follow-up reminders and optional memory ingest.
- Optional outgoing reply sending only after user approval.

Important safety constraints:

- Do not add automatic send behavior without explicit approval flow.
- Keep session strings encrypted.
- Respect per-user/day notification and follow-up limits.
- Use `topic_kwargs_for_user(user)` when sending back into a private topic.

### Telegram Private Topics

`User.tg_private_topic_id` stores the last private chat topic id observed by `DBSessionMiddleware`. Background sends should pass `**topic_kwargs_for_user(user)` so reminders/files/proactive messages land in the correct topic when Telegram topics are used.

### Subscriptions and Payments

Subscription status is derived by `SubscriptionService.get_user_status()`:

- `admin`: `tg_user_id` is in `ADMIN_USER_IDS`
- `premium`: `subscription_ends_at` is in the future
- `trial`: within `TRIAL_DAYS` after `created_at`
- `expired`: no active entitlement

`/subscribe` creates a Telegram Stars recurring invoice (`currency="XTR"`, `subscription_period=30 days`). Successful payments are validated, deduplicated by `telegram_payment_charge_id`, stored in `payments`, and extend `users.subscription_ends_at`.

Daily message quotas use Redis keys:

```text
quota:{user.id}:{YYYY-MM-DD}
```

### Gamification

Gamification is feature-flagged through `FEATURE_FLAGS_JSON` merged with `FEATURE_FLAG_DEFAULTS` in `app/services/gamification/schemas.py`.

Main pieces:

- `event_bus.py`: async in-process pub/sub, disabled unless `F002_EVENT_BUS=true`.
- `analytics_service.py`: global event sink into `gamification_events`.
- `gamification/xp_service.py`: XP and levels.
- `gamification/badge_service.py`: data-driven badge progress.
- `gamification/reward_service.py`: variable rewards and pity timer.
- `gamification/leaderboard_service.py`: leaderboard data.
- `streak_service.py`: message streak and freeze tokens.
- `milestone_service.py`, `memory_reveal_service.py`, `insight_service.py`, `premium_taste_service.py`: engagement features.

Post-chat gamification is intentionally best-effort. Failures are logged and must not break the chat handler.

### Row Integrity and Encryption

Sensitive columns use:

- `EncryptedTextType(column_label)`
- `EncryptedJSONType(column_label)`

The column label is Additional Authenticated Data and must not change after data exists.

`app/security/row_integrity.py` registers SQLAlchemy hooks from `db.py`. It calculates HMAC signatures for configured tracked rows and verifies them on load. `INTEGRITY_STRICT_MODE=true` rejects tracked rows that lack an integrity signature. Use `scripts/backfill_integrity_signatures.py` when adding integrity coverage or migrating existing rows.

### Database Sessions

Handlers receive `session` from `DBSessionMiddleware`. The middleware owns commit/rollback/close and also remembers private-topic ids before committing.

For service-layer or job code outside handlers, use:

```python
from app.db import get_session

async with get_session() as session:
    ...
```

or manage `AsyncSessionLocal()` explicitly when a job needs custom commit/rollback behavior.

Do not commit inside ordinary handler helpers unless the existing flow already requires it. Tool execution generally relies on the handler transaction.

## Configuration

Settings are in `app/config.py`. The `.env` loader ignores extra keys.

Important environment variables:

| Variable | Purpose |
|---|---|
| `ENV` | `dev` enables `create_all`; production uses migrations only |
| `LOG_LEVEL` | loguru level |
| `TELEGRAM_BOT_TOKEN` | Bot token |
| `TELEGRAM_WEBHOOK_SECRET` | Telegram webhook secret header |
| `PUBLIC_BASE_URL` | Public base URL for webhook |
| `TELEGRAM_API_PROXY` | Optional SOCKS proxy for Bot API |
| `TELEGRAM_USE_POLLING` | Run long polling instead of webhook |
| `DATABASE_URL` | async SQLAlchemy URL |
| `REDIS_URL` | Redis URL |
| `OPENROUTER_API_KEY` | OpenRouter key |
| `OPENROUTER_BASE_URL` | OpenRouter base URL |
| `LLM_MODEL_ID` | Main chat model |
| `AUDIO_IMAGE_MODEL_ID` | Vision/audio model |
| `EMBEDDING_MODEL_ID` | Embedding model |
| `EXTRACTOR_MODEL_ID` | Memory extractor model |
| `EPISODE_LIFETIME_DAYS` | Episode retention |
| `WORKING_MEMORY_LIFETIME_DAYS` | Working memory retention |
| `ENCRYPTION_KEY` | Fernet key |
| `DATA_ENCRYPTION_KEYSET_B64` | Tink AEAD keyset |
| `INTEGRITY_STRICT_MODE` | Row-integrity verification strictness |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` | Google Calendar OAuth |
| `ADMIN_USER_IDS` | comma-separated Telegram user ids |
| `SENTRY_DSN`, `ENABLE_METRICS` | monitoring |
| `MAX_MESSAGES_PER_MINUTE` | Telegram middleware rate limit |
| `TRIAL_DAYS` | trial length |
| `SUBSCRIPTION_PRICE_STARS` | Stars price per 30-day subscription |
| `LIMIT_TECHNICAL_SECONDS` | anti-spam delay |
| `LIMIT_DAILY_TRIAL`, `LIMIT_DAILY_PREMIUM`, `LIMIT_DAILY_EXPIRED` | chat quotas |
| `CODE_EXEC_DAILY_TRIAL`, `CODE_EXEC_DAILY_PREMIUM` | sandbox quotas |
| `TAVILY_API_KEY`, `SEARCH_CACHE_TTL`, `SEARCH_MAX_RESULTS` | search config |
| `SEARCH_DAILY_TRIAL`, `SEARCH_DAILY_PREMIUM` | search quotas |
| `NEWS_DIGEST_OFFSET_MINUTES` | digest offset after wake time |
| `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` | MTProto credentials |
| `USERBOT_*` | userbot limits, thresholds, follow-ups, style/context settings |
| `FEATURE_FLAGS_JSON` | JSON or comma-separated feature flag overrides |

## Development Workflow

Install dependencies:

```bash
poetry install
```

Prepare environment:

```bash
cp .env.example .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
python scripts/generate_data_keyset.py
```

Start infrastructure:

```bash
docker-compose up db redis -d
```

Apply migrations:

```bash
poetry run alembic upgrade head
```

Build sandbox images:

```bash
docker build -f docker/sandbox.Dockerfile -t motivi-sandbox:latest .
docker pull node:20-alpine
docker pull alpine:3
```

Run locally:

```bash
ENV=dev poetry run uvicorn app.main:app --reload --port 8000
```

Production-style Docker:

```bash
docker-compose up --build -d
docker-compose exec app alembic upgrade head
```

Tests and checks:

```bash
poetry run pytest tests/ -v
poetry run ruff check app tests
poetry run black app tests
poetry run mypy app
```

Tests expect real backing services where `tests/conftest.py` requires them.

## Adding Features

### New Bot Command

1. Add a router in `app/bot/routers/your_feature.py`.
2. Add states in `app/bot/states.py` if the flow is multi-step.
3. Put business logic in `app/services/your_service.py`.
4. Add models and an Alembic migration if persistence is needed.
5. Register the router in `app/bot/dispatcher.py` before catch-all routers.
6. Add command registration only if/when `app/bot/init.py` is used for command menu setup.

### New LLM Tool

1. Add `TOOL_*` schema in `app/llm/tool_schemas.py`.
2. Add it to `RAW_TOOLS`.
3. Add dispatch and implementation in `ToolExecutor.execute()`.
4. Apply subscription/rate limits if the tool consumes expensive or external resources.
5. Emit gamification events only through the feature-flagged event bus and keep failures non-fatal.

### New Skill

1. Add `app/skills/my-skill.md` with `name` and `description` frontmatter.
2. Include concrete execution patterns if the skill uses the sandbox.
3. No code change is normally needed; restart production processes to refresh metadata.

### New Model or Column

1. Update the SQLModel model.
2. Import the model in `init_db()` if dev `create_all` must see it.
3. Generate an Alembic migration:

```bash
poetry run alembic revision --autogenerate -m "description"
```

4. Review autogenerate output manually, especially pgvector indexes, encrypted columns, and server defaults.
5. If the column is sensitive, use encrypted types with a stable column label.
6. If the row participates in integrity checks, update `row_integrity.py` and provide a backfill path.

## Coding Conventions

- Use `from __future__ import annotations` in new Python modules.
- Prefer async APIs throughout.
- Use `loguru`, not stdlib logging.
- Use loguru placeholder formatting: `logger.info("User {}", user.id)`.
- Do not expose raw exception text to Telegram users.
- Bot parse mode is HTML by default. Use HTML tags and escape user-controlled content with `html.escape()` before embedding.
- Store DB datetimes as timezone-aware UTC.
- Use `zoneinfo.ZoneInfo` for new timezone code.
- Preserve existing dirty work. Do not revert unrelated changes.
- For Telegram background sends, pass `**topic_kwargs_for_user(user)` when a `User` is available.
- Keep handler side effects best-effort only when the surrounding code already follows that pattern.

## Important Files

| File | Purpose |
|---|---|
| `app/main.py` | FastAPI entry point, startup/shutdown, webhook/polling |
| `app/config.py` | Environment-driven settings and feature flags |
| `app/db.py` | Engine/session setup, pgvector, row integrity hooks |
| `app/bot/dispatcher.py` | Bot creation, middleware, router order |
| `app/bot/middlewares/db_session.py` | Handler transaction lifecycle and private-topic persistence |
| `app/llm/conversation_service.py` | Persona prompt and tool-calling loop |
| `app/llm/tool_schemas.py` | LLM tool definitions |
| `app/services/tool_executor.py` | LLM tool implementations |
| `app/services/proactive_planning_service.py` | Smart proactive planner |
| `app/services/userbot_monitor.py` | Telethon event processing |
| `app/services/userbot_thread_service.py` | Persistent userbot thread/follow-up logic |
| `app/services/subscription_service.py` | Trial/premium/admin/payment logic |
| `app/services/gamification/schemas.py` | Game events, XP constants, feature flags |
| `app/security/encrypted_types.py` | Encrypted DB types |
| `app/security/row_integrity.py` | Integrity signatures |
| `app/scheduler/job_manager.py` | Per-user job scheduling |
| `app/scheduler/jobs.py` | APScheduler job functions |
| `app/models/*.py` | SQLModel tables |
| `alembic/versions/` | Migration history |

## Alembic Migration History

Known migrations in this repo:

| Revision | Description |
|---|---|
| `803a95fd0d9e` | Initial structure |
| `16c8dbaee964` | Add created_at fields to core memory |
| `8edfc37203e1` | Add plans table |
| `962e790beaf7` | Add subscription fields |
| `fc08a8eb9107` | Add core fact and core fact embedding |
| `20251204_add_core_fact_table` | Add CoreFact table branch |
| `20251212_vector_4096` | Vector dimension to 4096 |
| `20260128_add_vector_indexes` | Vector indexes |
| `20260226_add_user_triggers` | User triggers |
| `20260228_add_search_news_digest_settings` | Search/news digest settings |
| `20260301_add_userbot_session_and_settings` | Userbot sessions/settings |
| `20260304_add_integrity_sig_columns` | Integrity signature columns |
| `20260310_add_gamification_system` | Gamification tables/fields |
| `20260314_add_bot_persona` | Bot persona setting/prompts |
| `20260314_add_userbot_reply_approval` | Userbot reply approval settings |
| `2213045bad38` | Merge integrity signature and bot persona heads |
| `51d1ea426c9b` | Merge heads |
| `20260427_add_payments_table` | Payment audit table |
| `20260501_add_smart_proactivity_settings` | Smart proactivity settings |
| `20260502_add_userbot_threads` | Persistent userbot threads |
| `20260507_add_private_topic_id_to_users` | Private topic id on users |

## Current Caveats

- `app/models/gamification.py` defines tables, but `init_db()` currently imports only the main runtime models. Production migrations remain the source of truth.
- Several text literals in source files display as mojibake in a non-UTF-8 PowerShell console. Read files with `-Encoding UTF8`.
- `persona_service.py` builds premium persona preference modifiers, but the main conversation path currently selects persona files through `ConversationService`.
- The working tree may contain uncommitted user changes. Inspect `git status --short` before editing and avoid reverting unrelated modifications.
