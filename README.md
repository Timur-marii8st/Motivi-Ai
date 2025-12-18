# Motivi_AI

<div align="center">

[🇺🇸 **English Version**](#english-version) | [🇷🇺 **Русская версия**](#русская-версия)

</div>

---

<a name="english-version"></a>
## 🇺🇸 English Version

**Motivi_AI** is a proactive, intelligent Telegram planning assistant powered by LLMs (Google Gemini). It helps users organize their day, track habits, manage memory (short-term and long-term), and stay motivated through personalized morning check-ins and evening wrap-ups.

### 🌟 Key Features

*   **🧠 Advanced Memory System**:
    *   **Core Memory**: Stores permanent facts about the user (goals, sleep schedule).
    *   **Episodic Memory**: RAG-based retrieval of past events and logs using vector embeddings.
    *   **Working Memory**: Tracks current context and short-term focus.
*   **🔄 Proactive Flows**: Automatically initiates conversations for morning planning, evening reflection, and weekly/monthly reviews based on the user's timezone.
*   **📅 Calendar Integration**: Seamless integration with **Google Calendar** to manage events and check availability.
*   **✅ Habit Tracking**: Create habits, set reminders, and track streaks.
*   **🎙️ Multimodal Support**: 
    *   **Voice**: Transcribes voice messages using **Whisper**.
    *   **Vision**: Analyzes photos using **Gemini Vision**.
*   **🔒 Privacy & Security**:
    *   **End-to-End Database Encryption**: Sensitive user data (text, JSON) is encrypted at rest using Tink AEAD/Fernet.
    *   **GDPR Compliant**: Full data export and account deletion commands.

### 🛠 Tech Stack

*   **Language**: Python 3.11
*   **Bot Framework**: Aiogram 3.x
*   **Web Server**: FastAPI (for Webhooks & OAuth)
*   **Database**: PostgreSQL 16 + `pgvector` (Async SQLAlchemy/SQLModel)
*   **Caching/Queue**: Redis (FSM Storage, Rate Limiting, History)
*   **LLM**: Google Gemini (via `google-genai` SDK) & Gemma
*   **Scheduler**: APScheduler
*   **Containerization**: Docker & Docker Compose

### 🚀 Getting Started

#### Prerequisites
*   Docker & Docker Compose
*   A Telegram Bot Token (from @BotFather)
*   Google Gemini API Key
*   Google Cloud Credentials (for Calendar integration)

#### Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/yourusername/motivi_ai.git
    cd motivi_ai
    ```

2.  **Environment Setup:**
    Copy the example environment file and fill in your credentials.
    ```bash
    cp .env.example .env
    ```
    *   Generate an encryption key:
        ```bash
        python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
        ```
    *   Generate Tink keyset for DB encryption:
        ```bash
        python scripts/generate_data_keyset.py
        ```
    *   Fill in `TELEGRAM_BOT_TOKEN`, `GEMINI_API_KEY`, `DATABASE_URL`, etc., in `.env`.

3.  **Run with Docker Compose:**
    ```bash
    docker-compose up --build -d
    ```

4.  **Initialize Database:**
    The migrations are handled by Alembic.
    ```bash
    docker-compose exec app alembic upgrade head
    ```

### 🤖 Usage

1.  Open your bot in Telegram.
2.  Send `/start` to begin the onboarding process (set name, city/timezone, wake/bed times). You can send `/skip` at any step to skip it and fill it later.
3.  **Commands:**
    *   `/profile` - View and edit your profile.
    *   `/habits` - Manage your habits.
    *   `/add_habit` - Create a new habit.
    *   `/connect_calendar` - Link Google Calendar.
    *   `/settings` - Toggle proactive features or "Break Mode".
    *   `/break [1d|off]` - Pause the bot for a specific duration.
    *   `/subscribe` - Purchase Premium (via Telegram Stars).

### 📂 Project Structure

*   `app/bot`: Telegram handlers, routers, and middleware.
*   `app/services`: Business logic (Memory, Habits, OAuth, etc.).
*   `app/models`: SQLModel database definitions.
*   `app/llm`: Interaction with Gemini and prompt management.
*   `mcp_server`: Separate service for Model Context Protocol tools.
*   `alembic`: Database migrations.

---

<a name="русская-версия"></a>
## 🇷🇺 Русская версия

**Motivi_AI** — это проактивный интеллектуальный ассистент по планированию в Telegram, работающий на базе LLM (Google Gemini). Бот помогает организовывать день, отслеживать привычки, управлять памятью (краткосрочной и долгосрочной) и поддерживать мотивацию с помощью персонализированных утренних и вечерних чек-инов.

### 🌟 Ключевые возможности

*   **🧠 Продвинутая система памяти**:
    *   **Core Memory (Базовая)**: Хранит постоянные факты о пользователе (цели, режим сна).
    *   **Episodic Memory (Эпизодическая)**: Поиск по прошлым событиям (RAG) с использованием векторных эмбеддингов.
    *   **Working Memory (Рабочая)**: Отслеживает текущий контекст и фокус на неделю.
*   **🔄 Проактивные сценарии**: Автоматически начинает диалог для утреннего планирования, вечернего подведения итогов и еженедельного обзора (учитывая часовой пояс пользователя).
*   **📅 Интеграция с календарем**: Подключение **Google Calendar** для управления событиями и проверки занятости.
*   **✅ Трекер привычек**: Создание привычек, настройка напоминаний, отслеживание серий (стриков).
*   **🎙️ Мультимодальность**:
    *   **Голос**: Транскрибация голосовых сообщений через **Whisper**.
    *   **Зрение**: Анализ фотографий через **Gemini Vision**.
*   **🔒 Приватность и безопасность**:
    *   **Шифрование БД**: Чувствительные данные (текст, JSON) шифруются в базе данных (Tink AEAD/Fernet).
    *   **Соответствие GDPR**: Возможность полной выгрузки данных или удаления аккаунта.

### 🛠 Технологический стек

*   **Язык**: Python 3.11
*   **Фреймворк бота**: Aiogram 3.x
*   **Веб-сервер**: FastAPI (Вебхуки и OAuth)
*   **База данных**: PostgreSQL 16 + `pgvector` (Async SQLAlchemy/SQLModel)
*   **Кэш/Очереди**: Redis (FSM, Rate Limiting, История диалогов)
*   **LLM**: Google Gemini (SDK `google-genai`) и Gemma
*   **Планировщик**: APScheduler
*   **Контейнеризация**: Docker и Docker Compose

### 🚀 Запуск проекта

#### Требования
*   Docker и Docker Compose
*   Токен Telegram бота (от @BotFather)
*   API ключ Google Gemini
*   Учетные данные Google Cloud (для календаря)

#### Установка

1.  **Клонируйте репозиторий:**
    ```bash
    git clone https://github.com/yourusername/motivi_ai.git
    cd motivi_ai
    ```

2.  **Настройка окружения:**
    Скопируйте пример файла конфигурации и заполните его.
    ```bash
    cp .env.example .env
    ```
    *   Сгенерируйте ключ шифрования:
        ```bash
        python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
        ```
    *   Сгенерируйте keyset для шифрования данных БД (Tink):
        ```bash
        python scripts/generate_data_keyset.py
        ```
    *   Заполните `TELEGRAM_BOT_TOKEN`, `GEMINI_API_KEY`, `DATABASE_URL` и другие переменные в `.env`.

3.  **Запуск через Docker Compose:**
    ```bash
    docker-compose up --build -d
    ```

4.  **Инициализация базы данных:**
    Миграции управляются через Alembic.
    ```bash
    docker-compose exec app alembic upgrade head
    ```

### 🤖 Использование

1.  Откройте бота в Telegram.
2.  Отправьте `/start` для начала онбординга (установка имени, возраста, часового пояса, режима сна).
3.  **Команды:**
    *   `/profile` — Просмотр и редактирование профиля.
    *   `/habits` — Управление привычками.
    *   `/add_habit` — Добавить новую привычку.
    *   `/connect_calendar` — Подключить Google Календарь.
    *   `/settings` — Настройки проактивности и "Режима тишины".
    *   `/break [1d|off]` — Приостановить бота на определенное время.
    *   `/subscribe` — Купить Премиум (через Telegram Stars).

### 📂 Структура проекта

*   `app/bot`: Хендлеры Telegram, роутеры и мидлвари.
*   `app/services`: Бизнес-логика (Память, Привычки, OAuth и т.д.).
*   `app/models`: Описание моделей базы данных (SQLModel).
*   `app/llm`: Взаимодействие с Gemini и управление промптами.
*   `mcp_server`: Отдельный сервис для инструментов (Model Context Protocol).
*   `alembic`: Миграции базы данных.