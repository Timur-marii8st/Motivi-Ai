# Motivi_AI

[Engineering walkthrough and six reproducible memory checks](docs/ENGINEERING_CASE.md) · [Разбор архитектуры и проверки памяти](docs/ENGINEERING_CASE.md)

<div align="center">

[🇺🇸 **English Version**](#english-version) | [🇷🇺 **Русская версия**](#русская-версия)

</div>

---

<a name="english-version"></a>
## 🇺🇸 English Version

**Motivi_AI** is a proactive, intelligent Telegram planning assistant powered by LLMs. It goes far beyond simple chatbots by implementing a sophisticated cognitive architecture with long-term memory, habit tracking, autonomous proactive planning, calendar integration, sandboxed code execution, web search, gamification, and a Telethon-based userbot for personal account monitoring.

### 🌟 Key Features

* **🧠 Three-Layer Cognitive Memory**:
    * **Core Memory**: Permanent facts about the user (personality, bio, goals). Retrieved semantically via `pgvector`.
    * **Episodic Memory**: Past conversation episodes with RAG-based retrieval.
    * **Working Memory**: Short-term summaries that decay over time.
* **🤖 Smart Proactivity**: An LLM-driven daily planner schedules one-off proactive touches (morning check-ins, evening wrap-ups, weekly/monthly reviews) based on the user's timezone and context. Old fixed-schedule jobs are deprecated.
* **📅 Google Calendar Integration**: Two-way sync — check availability and create events directly from chat via `/connect_calendar`.
* **✅ Habit Tracking**: Create habits with cadences, track streaks, and receive automated reminders.
* **🎙️ Multimodal**: Voice note transcription and photo analysis via Gemini models.
* **🔍 Web Search**: Real-time web and news search via Tavily API. Force search with prefixes `!!`, `!search`, or `!поиск`.
* **💻 Sandboxed Code Execution**: The LLM can run Python, JavaScript, and shell code inside isolated Docker containers with strict security limits (no network, read-only FS, memory/CPU caps).
* **🛠️ Agent Skills**: Progressive loading of 7 specialist skills (CV, data analysis, Excel, PowerPoint, project/study planning, Word docs) via Markdown files.
* **🤖 Telegram Userbot (MTProto)**: Connect your personal Telegram account via Telethon for read-only monitoring: channel post notifications, important DM/group notifications, and automatic extraction of deadlines/meetings into Motivi's internal calendar with reminders. Motivi never sends messages on your behalf.
* **📅 Internal Calendar**: Motivi keeps her own calendar inside the bot. Events are created automatically from messages and channel posts, via chat requests, or manually; each event gets an automatic reminder. Manage them with `/calendar`.
* **🎮 Gamification**: XP, levels, badges, leaderboards, message streaks, and variable rewards — feature-flagged and opt-in.
* **👤 Personas**: Choose a bot personality (`strict`, `friendly`, `coach`, `zen`, `hype`) via `/persona`.
* **🧩 Custom Triggers**: Users can define their own recurring proactive prompts (`/triggers`, `/add_trigger`), max 5 per user.
* **💎 Telegram Stars Subscriptions**: Trial → Premium flow with daily message quotas and rate-limited feature access.
* **🔒 Security & Privacy**:
    * **Field-Level Encryption**: Google Tink AEAD + Fernet for sensitive data at rest.
    * **Row Integrity**: HMAC signatures for tracked database rows.
    * **GDPR Compliance**: Full data export (`/export_data`) and account deletion.
* **👥 Group Chat Support**: Responds only when mentioned or replied to in groups/supergroups.
* **🔧 Admin Tools**: `/admin_stats`, `/admin_broadcast` for admin users.

### 🛠 Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11 |
| Telegram Bot | Aiogram 3.x |
| Web Server | FastAPI + Uvicorn |
| Database | PostgreSQL 16 + pgvector |
| ORM | SQLModel + SQLAlchemy 2.x async |
| DB Driver | asyncpg |
| LLM API | OpenRouter via `openai.AsyncOpenAI` |
| Embeddings | OpenRouter embedding API |
| Vision/Audio | Gemini via OpenRouter |
| Web Search | Tavily API |
| MTProto | Telethon |
| Scheduling | APScheduler 3.x AsyncIO + SQLAlchemy job store |
| State/Cache | Redis (FSM storage, conversation history, rate limiting) |
| Encryption | Google Tink AEAD + Fernet |
| Dependency Management | Poetry |
| Lint/Format/Type | Ruff, Black, mypy |
| Tests | pytest |
| Infra | Docker Compose + nginx-proxy-manager + optional sing-box proxy |

### 🚀 Installation & Setup

#### Prerequisites
* Docker & Docker Compose
* Telegram Bot Token (from @BotFather)
* OpenRouter API Key
* Tavily API Key (for web search)
* Google Cloud Credentials (for Calendar OAuth)
* Telegram API ID & Hash (from my.telegram.org, for userbot)

#### Steps

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/Timur-marii8st/Motivi-Ai.git
    cd Motivi-Ai
    ```

2.  **Environment Configuration:**
    ```bash
    cp .env.example .env
    ```
    Generate encryption keys:
    ```bash
    # Fernet Key
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    
    # Tink Keyset (for DB encryption)
    python scripts/generate_data_keyset.py
    ```
    Fill in `.env` with your API keys, tokens, and generated keys.

3.  **Build sandbox images** (required for code execution):
    ```bash
    docker build -f docker/sandbox.Dockerfile -t motivi-sandbox:latest .
    docker pull node:20-alpine
    docker pull alpine:3
    ```

4.  **Run with Docker:**
    ```bash
    docker-compose up --build -d
    ```

5.  **Apply Database Migrations:**
    ```bash
    docker-compose exec app alembic upgrade head
    ```

### 🤖 Bot Commands

Send `/commands` in Telegram for the full list. Key commands:

| Category | Commands |
|---|---|
| **General** | `/start`, `/help`, `/commands`, `/cancel`, `/settings`, `/profile`, `/break`, `/export_data` |
| **Habits & Plans** | `/habits`, `/add_habit`, `/log_habit <id>`, `/triggers`, `/add_trigger` |
| **Calendar & Memory** | `/calendar`, `/connect_calendar`, `/my_memories`, `/correct`, `/story`, `/persona` |
| **Userbot** | `/connect_userbot`, `/disconnect_userbot`, `/userbot_interests` |
| **Subscription & Progress** | `/subscribe`, `/referral`, `/level`, `/badges`, `/leaderboard` |
| **Admin** | `/admin_stats`, `/admin_broadcast` |

### 🤖 Userbot Monitoring & Calendar

The Telethon userbot monitors the connected account **read-only**: it never sends messages on behalf of the user. Incoming DMs and relevant group messages wait through a short debounce/read-check window before the LLM is called; already-read or already-answered messages are skipped.

Messages that pass these checks are classified. Important ones produce a notification, and any concrete dates/deadlines found in the text (meetings, calls, deadlines, dated events) are extracted into Motivi's internal calendar with automatic reminders. When a message expects an answer by a specific time, a "reply by" calendar event is created.

If the user replies manually from their Telegram account, the tracked thread is marked `replied` and the bot's notification is cleaned up. If the user only reads the message, the notification is removed. Channel posts are scored for relevance: high-scoring posts notify immediately (and feed the calendar), medium posts are batched into periodic digests.

### 📂 Project Structure

```
app/
  main.py                    # FastAPI entry point, lifespan, webhook/polling
  config.py                  # Pydantic settings & feature flags
  db.py                      # Async engine/session, pgvector, integrity hooks
  bot/
    dispatcher.py            # Bot/Dispatcher factory, middleware, router order
    bot_provider.py          # Global bot instance for scheduler jobs
    middlewares/
      db_session.py          # Per-update DB session + private-topic tracking
    routers/                 # Aiogram routers (19 routers by domain)
    states.py                # FSM states
  llm/
    client.py                # OpenRouter AsyncOpenAI singleton
    conversation_service.py  # ReAct tool loop with persona + memory
    tool_schemas.py          # OpenAI function-calling schemas (11 tools)
    gemini_client.py         # Secondary model client (vision/audio)
  services/
    memory_orchestrator.py   # Core + Working + Episodic memory assembly
    tool_executor.py         # Implementation of all LLM tools
    conversation_history_service.py  # Redis-backed chat history
    proactive_planning_service.py    # Smart LLM planner
    userbot_manager.py       # Telethon lifecycle
    userbot_monitor.py       # Channel/DM/group event handlers + calendar extraction
    userbot_thread_service.py# Persistent thread/notification tracking
    calendar_service.py      # Internal calendar CRUD + LLM event extraction
    subscription_service.py  # Trial/premium/admin status & payments
    event_bus.py             # Feature-flagged async domain event bus
    analytics_service.py     # Gamification event persistence
    gamification/            # XP, badges, rewards, leaderboard, streaks
    persona_service.py       # Premium persona preference modifier
    code_executor_service.py # Sandboxed Docker code execution
    search_service.py        # Tavily web search with Redis caching
    skills_service.py        # Agent skill progressive loading
    ...
  models/                    # SQLModel table definitions
  scheduler/                 # APScheduler singleton, job manager, jobs
  prompts/
    personas/*.txt           # Persona-specific system prompts (ru/en)
    moti_system*.txt         # Legacy fallback prompts
    gemma_system*.txt        # Extractor prompts
  security/
    encrypted_types.py       # Encrypted SQLAlchemy TypeDecorators
    encryption_manager.py    # Tink AEAD singleton
    row_integrity.py         # HMAC row integrity signatures
  skills/*.md                # Runtime agent skills exposed to the LLM
  embeddings/                # Embedding client
  integrations/              # Google Calendar OAuth
  jobs/                      # Background job functions
  utils/                     # Timezone, validators, encryption helpers
alembic/versions/            # Migration history
docs/                        # Architecture & infra notes
scripts/                     # Key generation, backfills, DB helpers
tests/                       # pytest suite
docker/                      # App and sandbox Dockerfiles
singbox/                     # Proxy example config
```

### ⚙️ Configuration Highlights

Key env variables (see `.env.example` for the full list):

| Variable | Purpose |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather |
| `OPENROUTER_API_KEY` | OpenRouter API key |
| `TAVILY_API_KEY` | Tavily API key for web search |
| `DATABASE_URL` | async PostgreSQL URL |
| `REDIS_URL` | Redis connection URL |
| `ENCRYPTION_KEY` | Fernet key (32 url-safe base64 bytes) |
| `DATA_ENCRYPTION_KEYSET_B64` | Tink AEAD keyset |
| `INTEGRITY_STRICT_MODE` | Row-integrity verification strictness |
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` | MTProto credentials for userbot |
| `FEATURE_FLAGS_JSON` | Gamification/feature flag overrides |

---

<a name="русская-версия"></a>
## 🇷🇺 Русская версия

**Motivi_AI** — это проактивный интеллектуальный ассистент для планирования в Telegram, работающий на базе LLM. Бот обладает сложной когнитивной архитектурой с долгосрочной памятью, трекером привычек, автономным планировщиком, интеграцией с календарём, песочницей для кода, веб-поиском, геймификацией и юзерботом для мониторинга личного аккаунта.

### 🌟 Ключевые возможности

* **🧠 Трёхуровневая когнитивная память**:
    * **Core Memory (Базовая)**: Постоянные факты о пользователе. Семантический поиск через `pgvector`.
    * **Episodic Memory (Эпизодическая)**: История диалогов с RAG-ретривалом.
    * **Working Memory (Рабочая)**: Краткосрочный контекст со временем угасания.
* **🤖 Умная проактивность**: LLM-планировщик ежедневно решает, какие сообщения будут полезны пользователю, и планирует разовые касания (утреннее планирование, вечерние итоги, еженедельные/ежемесячные обзоры). Старые фиксированные джобы устарели.
* **📅 Google Calendar**: Двусторонняя интеграция — проверка занятости и создание событий прямо из чата через `/connect_calendar`.
* **✅ Трекер привычек**: Создание привычек с расписанием, отслеживание стриков, автоматические напоминания.
* **🎙️ Мультимодальность**: Транскрибация голосовых сообщений и анализ фото через Gemini.
* **🔍 Веб-поиск**: Поиск в интернете и новостей через Tavily API. Принудительный поиск префиксами `!!`, `!search`, `!поиск`.
* **💻 Песочница для кода**: LLM может запускать Python, JavaScript и shell-код в изолированных Docker-контейнерах с жёсткими лимитами безопасности.
* **🛠️ Агентские скиллы**: Прогрессивная загрузка 7 специалистских навыков (CV, анализ данных, Excel, PowerPoint, планировщик проектов/учёбы, Word) через Markdown-файлы.
* **🤖 Юзербот (MTProto)**: Подключение личного Telegram-аккаунта через Telethon в режиме read-only: уведомления о постах каналов и важных сообщениях, автоматическое извлечение дедлайнов и встреч во внутренний календарь Мотиви с напоминаниями. Мотиви никогда не отправляет сообщения от вашего имени.
* **📅 Внутренний календарь**: У Мотиви свой календарь внутри бота. События создаются автоматически из сообщений людей и каналов, по просьбе в чате или вручную; у каждого события автоматическое напоминание. Управление — через `/calendar`.
* **🎮 Геймификация**: XP, уровни, значки, лидерборды, стрики сообщений и переменные награды — под фиче-флагами и по желанию.
* **👤 Персонажи**: Выбор личности бота (`strict`, `friendly`, `coach`, `zen`, `hype`) через `/persona`.
* **🧩 Пользовательские триггеры**: Собственные регулярные проактивные напоминания (`/triggers`, `/add_trigger`), максимум 5 на пользователя.
* **💎 Подписки через Telegram Stars**: Поток Trial → Premium с дневными квотами сообщений и рейт-лимитами функций.
* **🔒 Безопасность и приватность**:
    * **Шифрование на уровне полей**: Google Tink AEAD + Fernet.
    * **Целостность строк**: HMAC-подписи для отслеживаемых таблиц.
    * **GDPR**: Полный экспорт данных (`/export_data`) и удаление аккаунта.
* **👥 Работа в группах**: Отвечает только при упоминании или ответе на своё сообщение.
* **🔧 Админские инструменты**: `/admin_stats`, `/admin_broadcast`.

### 🛠 Технологический стек

| Слой | Технология |
|---|---|
| Язык | Python 3.11 |
| Telegram-фреймворк | Aiogram 3.x |
| Веб-сервер | FastAPI + Uvicorn |
| База данных | PostgreSQL 16 + pgvector |
| ORM | SQLModel + SQLAlchemy 2.x async |
| Драйвер БД | asyncpg |
| LLM API | OpenRouter через `openai.AsyncOpenAI` |
| Эмбеддинги | OpenRouter embedding API |
| Vision/Audio | Gemini через OpenRouter |
| Веб-поиск | Tavily API |
| MTProto | Telethon |
| Планировщик | APScheduler 3.x AsyncIO + SQLAlchemy job store |
| Кэш/состояния | Redis (FSM, история диалогов, рейт-лимиты) |
| Шифрование | Google Tink AEAD + Fernet |
| Управление зависимостями | Poetry |
| Линтинг/формат/типы | Ruff, Black, mypy |
| Тесты | pytest |
| Инфраструктура | Docker Compose + nginx-proxy-manager + опциональный sing-box |

### 🚀 Установка и запуск

#### Требования
* Docker и Docker Compose
* Токен Telegram-бота (от @BotFather)
* API-ключ OpenRouter
* API-ключ Tavily (для поиска)
* Учётные данные Google Cloud (для OAuth календаря)
* Telegram API ID и Hash (с my.telegram.org, для юзербота)

#### Инструкция

1.  **Клонируйте репозиторий:**
    ```bash
    git clone https://github.com/Timur-marii8st/Motivi-Ai.git
    cd Motivi-Ai
    ```

2.  **Настройка окружения:**
    ```bash
    cp .env.example .env
    ```
    Сгенерируйте ключи шифрования:
    ```bash
    # Fernet-ключ
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    
    # Tink Keyset (для шифрования БД)
    python scripts/generate_data_keyset.py
    ```
    Заполните `.env` своими API-ключами, токенами и сгенерированными ключами.

3.  **Соберите образы песочницы** (нужно для выполнения кода):
    ```bash
    docker build -f docker/sandbox.Dockerfile -t motivi-sandbox:latest .
    docker pull node:20-alpine
    docker pull alpine:3
    ```

4.  **Запуск через Docker:**
    ```bash
    docker-compose up --build -d
    ```

5.  **Применение миграций БД:**
    ```bash
    docker-compose exec app alembic upgrade head
    ```

### 🤖 Команды бота

Отправь `/commands` в Telegram для полного списка. Основные команды:

| Категория | Команды |
|---|---|
| **Основное** | `/start`, `/help`, `/commands`, `/cancel`, `/settings`, `/profile`, `/break`, `/export_data` |
| **Привычки и планы** | `/habits`, `/add_habit`, `/log_habit <id>`, `/triggers`, `/add_trigger` |
| **Календарь и память** | `/calendar`, `/connect_calendar`, `/my_memories`, `/correct`, `/story`, `/persona` |
| **Юзербот** | `/connect_userbot`, `/disconnect_userbot`, `/userbot_interests` |
| **Подписка и прогресс** | `/subscribe`, `/referral`, `/level`, `/badges`, `/leaderboard` |
| **Админ** | `/admin_stats`, `/admin_broadcast` |

### 🤖 Мониторинг юзербота и календарь

Telethon-юзербот отслеживает подключённый аккаунт **только для чтения**: он никогда не отправляет сообщения от имени пользователя. Входящие ЛС и релевантные сообщения в группах проходят короткое окно debounce/read-check перед вызовом LLM; уже прочитанные или уже отвеченные сообщения пропускаются.

Сообщения, прошедшие проверки, классифицируются. Важные порождают уведомление, а найденные в тексте конкретные даты и дедлайны (встречи, звонки, дедлайны, события с датой) извлекаются во внутренний календарь Мотиви с автоматическими напоминаниями. Если сообщение ждёт ответа к определённому времени, создаётся событие календаря «ответить до».

Если пользователь отвечает вручную из своего Telegram-аккаунта, тред помечается как `replied`, а уведомление бота убирается. Если пользователь только прочитал сообщение, уведомление удаляется. Посты каналов оцениваются по релевантности: высокооценённые сразу уведомляют (и питают календарь), среднеоценённые собираются в периодические дайджесты.

### 📂 Структура проекта

```
app/
  main.py                    # FastAPI: lifespan, webhook/polling, health
  config.py                  # Pydantic-настройки и фиче-флаги
  db.py                      # Асинхронный движок/сессия, pgvector, хуки целостности
  bot/
    dispatcher.py            # Фабрика Bot/Dispatcher, middleware, порядок роутеров
    bot_provider.py          # Глобальный инстанс бота для джоб планировщика
    middlewares/
      db_session.py          # Сессия БД на обновление + отслеживание topic
    routers/                 # 19 роутеров Aiogram по доменам
    states.py                # FSM-состояния
  llm/
    client.py                # Синглтон OpenRouter AsyncOpenAI
    conversation_service.py  # ReAct-цикл с персоной и памятью
    tool_schemas.py          # Схемы функций OpenAI (11 инструментов)
    gemini_client.py         # Вторичный клиент для vision/audio
  services/
    memory_orchestrator.py   # Сборка Core + Working + Episodic памяти
    tool_executor.py         # Реализация всех LLM-инструментов
    conversation_history_service.py  # История диалогов в Redis
    proactive_planning_service.py    # Умный LLM-планировщик
    userbot_manager.py       # Жизненный цикл Telethon
    userbot_monitor.py       # Обработчики событий каналов/ЛС/групп + извлечение в календарь
    userbot_thread_service.py# Персистентные треды и уведомления
    calendar_service.py      # Внутренний календарь: CRUD + LLM-извлечение событий
    subscription_service.py  # Логика trial/premium/admin и платежей
    event_bus.py             # Асинхная шина событий под фиче-флагами
    analytics_service.py     # Персистентность геймификационных событий
    gamification/            # XP, значки, награды, лидерборд, стрики
    persona_service.py       # Модификаторы премиум-персон
    code_executor_service.py # Песочница Docker для кода
    search_service.py        # Веб-поиск Tavily с кэшированием в Redis
    skills_service.py        # Прогрессивная загрузка скиллов
    ...
  models/                    # Определения таблиц SQLModel
  scheduler/                 # Синглтон APScheduler, менеджер джоб, функции джоб
  prompts/
    personas/*.txt           # Системные промпты персон (ru/en)
    moti_system*.txt         # Legacy fallback промпты
    gemma_system*.txt        # Промпты экстрактора
  security/
    encrypted_types.py       # Encrypted TypeDecorators SQLAlchemy
    encryption_manager.py    # Синглтон Tink AEAD
    row_integrity.py         # HMAC-подписи целостности строк
  skills/*.md                # Агентские скиллы, доступные LLM
  embeddings/                # Клиент эмбеддингов
  integrations/              # OAuth Google Calendar
  jobs/                      # Фоновые джобы
  utils/                     # Таймзоны, валидаторы, хелперы шифрования
alembic/versions/            # История миграций
docs/                        # Архитектура и инфраструктура
scripts/                     # Генерация ключей, бэкфиллы, хелперы БД
tests/                       # pytest
docker/                     # Dockerfile приложения и песочницы
singbox/                     # Пример конфига прокси
```

### ⚙️ Ключевые переменные окружения

Основные переменные (полный список в `.env.example`):

| Переменная | Назначение |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Токен бота от @BotFather |
| `OPENROUTER_API_KEY` | Ключ OpenRouter |
| `TAVILY_API_KEY` | Ключ Tavily для веб-поиска |
| `DATABASE_URL` | async URL PostgreSQL |
| `REDIS_URL` | URL подключения к Redis |
| `ENCRYPTION_KEY` | Fernet-ключ (32 url-safe base64 байта) |
| `DATA_ENCRYPTION_KEYSET_B64` | Tink AEAD keyset |
| `INTEGRITY_STRICT_MODE` | Строгость проверки целостности строк |
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` | MTProto-креденшелы для юзербота |
| `FEATURE_FLAGS_JSON` | Переопределения фиче-флагов (геймификация) |
