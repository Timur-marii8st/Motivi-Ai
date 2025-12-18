# Motivi_AI

<div align="center">

[🇺🇸 **English Version**](#english-version) | [🇷🇺 **Русская версия**](#русская-версия)

</div>

---

<a name="english-version"></a>
## 🇺🇸 English Version

**Motivi_AI** is a proactive, intelligent Telegram planning assistant powered by LLMs(Grok 4.1 Fast as main). It goes beyond simple chat bots by implementing a sophisticated cognitive architecture with long-term memory, habit tracking, and calendar integration to help users organize their lives and stay motivated.

### 🌟 Key Features

* **🧠 Cognitive Memory Architecture**:
    * **Core Memory**: Stores permanent facts about the user (personality, bio, long-term goals).
    * **Episodic Memory**: Uses RAG (Qwen 3 Embeddings) (Retrieval-Augmented Generation) with `pgvector` to recall past events and conversations.
    * **Working Memory**: Maintains short-term context, current focus, and weekly summaries that decay over time.
* **🔄 Proactive Flows**: The bot autonomously initiates conversations for **Morning Check-ins** (planning), **Evening Wrap-ups** (reflection), and **Weekly/Monthly Reviews** based on the user's specific timezone.
* **📅 Calendar Integration**: Seamless 2-way integration with **Google Calendar** to check availability and schedule events directly from chat.
* **✅ Habit Tracking**: Create habits with specific cadences (daily/weekly), track streaks, and receive automated reminders if a habit hasn't been logged yet.
* **🎙️ Multimodal Capabilities**:
    * **Voice**: Transcribes voice notes into text using Gemini 2.0 flash lite.
    * **Vision**: Analyzes photos to understand context using Gemini 2.0 flash lite.
* **🔒 Security & Privacy**:
    * **Field-Level Encryption**: Sensitive user data (text and JSON) is encrypted at rest in the database using **Google Tink (AEAD)**.
    * **GDPR Compliance**: Includes full data export and account deletion features.
* **💎 Subscription System**: Integration with **Telegram Stars** for Premium features.

### 🛠 Tech Stack

* **Core**: Python 3.11, Aiogram 3.x.
* **Database**: PostgreSQL 16 + `pgvector` (Async SQLAlchemy/SQLModel).
* **Infrastructure**: Docker & Docker Compose.
* **LLM**:  OpenRouter (Gemma/Grok/Gemini/Qwen).
* **Scheduling**: APScheduler (AsyncIO).
* **Security**: Google Tink, Fernet, Pydantic.

### 🚀 Installation & Setup

#### Prerequisites
* Docker & Docker Compose
* Telegram Bot Token (from @BotFather)
* Google Gemini API Key / OpenRouter Key
* Google Cloud Credentials (`client_secret.json` content for Calendar)

#### Steps

1.  **Clone the repository:**
    ```bash
    git clone [https://github.com/yourusername/motivi_ai.git](https://github.com/yourusername/motivi_ai.git)
    cd motivi_ai
    ```

2.  **Environment Configuration:**
    Copy the example file:
    ```bash
    cp .env.example .env
    ```
    **Important:** You must generate encryption keys for the app to work:
    ```bash
    # Generate Fernet Key
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    
    # Generate Tink Keyset (for DB encryption)
    python scripts/generate_data_keyset.py
    ```
    Paste these values into `ENCRYPTION_KEY` and `DATA_ENCRYPTION_KEYSET_B64` in your `.env` file, along with your API keys and Database URL.

3.  **Run with Docker:**
    ```bash
    docker-compose up --build -d
    ```

4.  **Apply Database Migrations:**
    ```bash
    docker-compose exec app alembic upgrade head
    ```

### 🤖 Usage

1.  Open your bot in Telegram.
2.  Send `/start` to begin the onboarding process (set name, age, timezone, wake/bed times).
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

**Motivi_AI** — это проактивный интеллектуальный ассистент для планирования в Telegram, работающий на базе LLM (Grok 4.1 Fast как основная). Бот не просто отвечает на вопросы, а обладает сложной когнитивной архитектурой с долгосрочной памятью, трекером привычек и интеграцией с календарем, помогая пользователям организовывать жизнь и сохранять мотивацию.

### 🌟 Ключевые возможности

* **🧠 Когнитивная архитектура памяти**:
    * **Core Memory (Базовая)**: Хранит неизменные факты о пользователе (личность, биография, долгосрочные цели).
    * **Episodic Memory (Эпизодическая)**: Использует RAG (Qwen 3 Embeddings) (поиск по векторам) через `pgvector` для запоминания прошлых событий и диалогов.
    * **Working Memory (Рабочая)**: Хранит краткосрочный контекст, текущий фокус и еженедельные сводки, которые "угасают" со временем.
* **🔄 Проактивные сценарии**: Бот сам начинает диалог для **Утреннего планирования**, **Вечернего подведения итогов** и **Еженедельного/Ежемесячного обзора** в зависимости от часового пояса пользователя.
* **📅 Календарь**: Двусторонняя интеграция с **Google Calendar** для проверки занятости и создания событий прямо из чата.
* **✅ Трекер привычек**: Создание привычек с расписанием (ежедневно/еженедельно), отслеживание стриков (серий) и автоматические напоминания, если привычка еще не выполнена.
* **🎙️ Мультимодальность**:
    * **Голос**: Транскрибация голосовых сообщений в текст (Gemini).
    * **Зрение**: Анализ фотографий для понимания контекста через Gemini.
* **🔒 Безопасность и Приватность**:
    * **Шифрование данных**: Чувствительные данные (текст переписки, JSON) шифруются в базе данных с помощью **Google Tink (AEAD)**.
    * **GDPR**: Поддержка полной выгрузки данных и удаления аккаунта.
* **💎 Система подписок**: Интеграция с **Telegram Stars** для Премиум-функций.

### 🛠 Технологический стек

* **Ядро**: Python 3.11, Aiogram 3.x.
* **База данных**: PostgreSQL 16 + `pgvector` (Async SQLAlchemy/SQLModel).
* **Инфраструктура**: Docker & Docker Compose.
* **LLM**: Google Gemini (через `google-genai`) и OpenRouter (Gemma/Grok/Gemini/Qwen).
* **Планировщик**: APScheduler (AsyncIO).
* **Безопасность**: Google Tink, Fernet, Pydantic.

### 🚀 Установка и запуск

#### Требования
* Docker и Docker Compose
* Токен Telegram бота (от @BotFather)
* API ключ Google Gemini / OpenRouter
* Учетные данные Google Cloud (содержимое `client_secret.json` для календаря)

#### Инструкция

1.  **Клонируйте репозиторий:**
    ```bash
    git clone [https://github.com/yourusername/motivi_ai.git](https://github.com/yourusername/motivi_ai.git)
    cd motivi_ai
    ```

2.  **Настройка окружения:**
    Скопируйте пример конфига:
    ```bash
    cp .env.example .env
    ```
    **Важно:** Сгенерируйте ключи шифрования для работы приложения:
    ```bash
    # Генерация Fernet ключа
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    
    # Генерация Tink Keyset (для шифрования БД)
    python scripts/generate_data_keyset.py
    ```
    Вставьте полученные значения в `ENCRYPTION_KEY` и `DATA_ENCRYPTION_KEYSET_B64` в файле `.env`, а также укажите ваши API ключи и URL базы данных.

3.  **Запуск через Docker:**
    ```bash
    docker-compose up --build -d
    ```

4.  **Применение миграций БД:**
    ```bash
    docker-compose exec app alembic upgrade head
    ```

### 🤖 Команды бота

* `/start` — Начать онбординг (Имя, Возраст, Часовой пояс, Режим сна).
* `/profile` — Просмотр/редактирование профиля или удаление аккаунта.
* `/habits` — Просмотр активных привычек и стриков.
* `/add_habit` — Создание новой привычки.
* `/connect_calendar` — Авторизация Google Календаря.
* `/settings` — Настройка проактивных сообщений или "Режима тишины".
* `/subscribe` — Покупка Премиума за Telegram Stars.
* `/break [1d|off]` — Приостановить работу бота на указанное время.
