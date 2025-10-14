# Motivi_AI

**Motivi_AI** is an AI-powered planning assistant Telegram bot with proactive scheduling, habit tracking, multimodal input, and deep memory integration.

## Features

✅ **Multi-layered Memory System**: Core, Working, and Episodic memory with RAG  
✅ **Proactive Interactions**: Morning check-ins, evening wrap-ups, weekly/monthly plans  
✅ **Habit Tracking**: Streak tracking, reminders, statistics  
✅ **Multimodal Input**: Voice (Whisper STT), Photo (Gemini Vision), Text  
✅ **Google Calendar Integration**: OAuth2, event creation, availability checks  
✅ **User Control**: Profile management, settings, break mode, data export  
✅ **Adaptive Questioning**: Smart question frequency based on profile completeness  
✅ **Tool Calling**: LLM agent with MCP server for document generation and Telegram actions  

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Telegram Bot Token (from [@BotFather](https://t.me/BotFather))
- Google Gemini API Key
- Google OAuth credentials (for Calendar integration)

### Setup

1. **Clone and configure:**

```bash
git clone <repo-url>
cd motivi_ai
cp .env.example .env
```

2. **Edit `.env`** with your tokens and secrets

3. **Generate encryption key:**

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Add to `.env` as `ENCRYPTION_KEY`

4. **Start services:**

```bash
docker compose up -d --build
```

6. **Set webhook** (update `PUBLIC_BASE_URL` in `.env` first):

Webhook is set automatically on app startup.

7. **Start chatting** with your bot on Telegram!

## Commands

- `/start` - Onboard and set up profile
- `/profile` - View and edit your profile
- `/settings` - Configure notifications and proactivity
- `/break [duration|off]` - Activate/deactivate break mode
- `/habits` - List your habits
- `/add_habit` - Create a new habit
- `/log_habit <id>` - Log habit completion
- `/connect_calendar` - Link Google Calendar
- `/export_data` - Download your data (GDPR)
- `/help` - Show help message

## Architecture

```
Telegram User
     ↓
Webhook (FastAPI)
     ↓
Bot Dispatcher (aiogram)
     ↓
┌────────────┬────────────┬──────────┐
│  Memory    │ LLM Agent  │  Tools   │
│  System    │  (Gemini)  │  (MCP)   │
└────────────┴────────────┴──────────┘
     ↓              ↓            ↓
PostgreSQL      Scheduler    External APIs
+ pgvector                   (Calendar, etc.)
```

## Development

### Run tests:

```bash
docker compose exec app poetry run pytest tests/ -v
```

### View logs:

```bash
docker compose logs -f app
```

### Access database:

```bash
docker compose exec db psql -U postgres -d motivi
```

## Production Deployment

See `docker-compose.prod.yml` and `scripts/deploy.sh`.

Ensure:
- SSL certificates (Let's Encrypt)
- Secure `.env.prod` with strong secrets
- Persistent volumes for database
- HTTPS webhook URL
- Admin user IDs configured

## License

MIT

## Support

For issues, open a GitHub issue or contact the maintainers.
```

**RUNBOOK.md** (operations guide):

```markdown
# Motivi_AI Runbook

## Health Checks

### Application health:
```bash
curl https://your-domain.com/health
```

Expected: `{"status": "ok", "scheduler_running": true, "jobs_count": N}`

### Database:
```bash
docker compose exec db psql -U postgres -d motivi -c "SELECT COUNT(*) FROM users;"
```

### Scheduler jobs:
```bash
docker compose exec app poetry run python scripts/list_jobs.py
```

## Common Issues

### Webhook not receiving updates

1. Check PUBLIC_BASE_URL is HTTPS and accessible
2. Verify TELEGRAM_WEBHOOK_SECRET matches
3. Check Telegram webhook info:
```bash
curl https://api.telegram.org/bot<TOKEN>/getWebhookInfo
```

### Jobs not running

1. Check scheduler status in `/health`
2. Verify user timezone is valid IANA format
3. Check job logs:
```bash
docker compose logs app | grep "Running.*job"
```


## Backup & Restore

### Backup database:
```bash
docker compose exec db pg_dump -U postgres motivi > backup_$(date +%Y%m%d).sql
```

### Restore:
```bash
cat backup_YYYYMMDD.sql | docker compose exec -T db psql -U postgres motivi
```

## Scaling

For >1000 users:
- Move to managed PostgreSQL (RDS, Cloud SQL)
- Add Redis for rate limiting and caching
- Use Celery workers for background jobs instead of APScheduler
- Enable `ENABLE_METRICS=true` and monitor with Prometheus/Grafana

## Monitoring

- Health endpoint: `/health`
- Metrics: `/metrics` (if ENABLE_METRICS=true)
- Logs: structured JSON via loguru
- Optional: Sentry integration (set SENTRY_DSN)

## Security Checklist

✅ ENCRYPTION_KEY rotated and stored securely  
✅ TELEGRAM_WEBHOOK_SECRET is random and strong  
✅ MCP_SECRET_TOKEN is random and strong  
✅ Database credentials are strong  
✅ Admin user IDs restricted  
✅ SSL/TLS enabled  
✅ Rate limiting active  