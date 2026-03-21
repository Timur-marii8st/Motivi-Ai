# Phase 0: Conductor Briefing

## Repository Overview
Motivi_AI is a proactive Telegram planning assistant (~17K lines Python across 133 files) built on Aiogram 3.x + FastAPI with a ReAct tool-calling loop powered by OpenRouter LLMs. It features a three-layer cognitive memory system (Core/Working/Episodic with pgvector RAG), habit tracking, Google Calendar integration, sandboxed code execution, web search, agent skills, a read-only Telegram userbot (Telethon/MTProto), gamification, persona system, and autonomous scheduled interactions (morning/evening check-ins, weekly reviews, news digests, custom triggers). Data is stored in PostgreSQL 16 + pgvector with Redis for FSM state, conversation history, and rate limiting. Field-level encryption uses Google Tink AEAD.

## Technology Stack
- **Language**: Python 3.11
- **Telegram**: Aiogram 3.x (webhook mode)
- **Web**: FastAPI + Uvicorn
- **Database**: PostgreSQL 16 + pgvector, SQLModel + SQLAlchemy 2.x (async), asyncpg
- **Cache/State**: Redis (FSM, history, rate limiting)
- **LLM**: OpenRouter (OpenAI-compatible), multiple models (Grok, Gemini Flash, Gemma, Qwen embeddings)
- **Scheduling**: APScheduler 3.x (AsyncIO)
- **Encryption**: Google Tink AEAD + Fernet
- **Infrastructure**: Docker Compose, Alembic migrations
- **Testing**: pytest (5 test files)
- **Linting**: Ruff, Black, mypy

## Top-Level Modules
1. `app/bot/routers/` — 16 Telegram command routers
2. `app/services/` — 30+ service modules (business logic)
3. `app/llm/` — LLM client, conversation service, tool schemas
4. `app/models/` — 12 SQLModel table definitions
5. `app/scheduler/` — APScheduler jobs and job manager
6. `app/security/` — Encryption, row integrity
7. `app/skills/` — 7 agent skill markdown files
8. `app/prompts/` — System prompts + 10 persona files
9. `app/utils/` — Timezone, validators, encryption helpers
10. `app/integrations/` — Google Calendar
11. `app/embeddings/` — Embedding client
12. `alembic/versions/` — 16 migration files

## Estimated Risk Zones
1. **`app/llm/conversation_service.py`** — Core ReAct loop, complex async orchestration, tool dispatch
2. **`app/services/tool_executor.py`** — Dispatches all tool calls, high blast radius
3. **`app/services/code_executor_service.py`** — Docker sandbox execution, security-critical
4. **`app/services/userbot_monitor.py`** — Telethon event handlers, external API interactions
5. **`app/services/userbot_manager.py`** — MTProto client lifecycle management
6. **`app/security/`** — Encryption/integrity, any bug here = data loss/exposure
7. **`app/scheduler/jobs.py`** — Scheduled job functions, error handling critical for reliability
8. **`app/main.py`** — Entry point, lifespan management, webhook handling
9. **`app/services/memory_orchestrator.py`** — Memory assembly, performance-critical path
10. **`app/config.py`** — Configuration, secrets management

## Agent Deployment Plan (Phase 1)
Deploy all 8 agents in parallel:
- Agent 1 (Bug Hunter): Focus on services/, llm/, scheduler/, bot/routers/
- Agent 2 (Security Auditor): Focus on security/, services/code_executor, config, userbot, encryption
- Agent 3 (Performance Analyst): Focus on memory_orchestrator, conversation_service, DB queries, embeddings
- Agent 4 (Architecture Reviewer): Full codebase structure, module boundaries, coupling
- Agent 5 (Test Coverage Inspector): tests/ directory + coverage gap analysis
- Agent 6 (Code Quality Auditor): All Python files, style, complexity, dead code
- Agent 7 (Dependency & Infra Analyst): pyproject.toml, Docker, alembic, CI/CD
- Agent 8 (Growth & Opportunity Scout): Features, DX, roadmap alignment
