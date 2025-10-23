from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    ENV: str = "dev"
    LOG_LEVEL: str = "INFO"

    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_WEBHOOK_SECRET: str
    PUBLIC_BASE_URL: str

    DATABASE_URL: str = Field(..., description="SQLAlchemy async URL, e.g., postgresql+asyncpg://...")

    GEMINI_API_KEY: str
    GEMINI_MODEL_ID: str
    GEMINI_EMBEDDING_MODEL_ID: str

    GEMMA_MODEL_ID: str
    # Allow GEMMA_API_KEY to be unset; if not provided we'll fallback to GEMINI_API_KEY
    GEMMA_API_KEY: str | None = None
    
        # Lifetime settings (in days)
    EPISODE_LIFETIME_DAYS: float = 2.5 * 30.0 / 30.0  # 2.5 months ~ 75 days (keep float for clarity)
    WORKING_MEMORY_LIFETIME_DAYS: int = 5

    MCP_BASE_URL: str = "http://mcp_server:8001"
    MCP_SECRET_TOKEN: str

    ENCRYPTION_KEY: str = Field(..., description="Must be 32 url-safe base64-encoded bytes")  # Must be 32 url-safe base64-encoded bytes
    
    # Google OAuth
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/oauth/google/callback"  # Update for production

    # Admin
    ADMIN_USER_IDS: str = ""  # Comma-separated Telegram user IDs
    
    # Monitoring
    SENTRY_DSN: str = ""
    ENABLE_METRICS: bool = False
    
    # Rate limiting
    MAX_MESSAGES_PER_MINUTE: int = 15

    REDIS_URL: str = "redis://redis:6379/0"
    
    @property
    def admin_ids(self) -> list[int]:
        if not self.ADMIN_USER_IDS:
            return []
        return [int(x.strip()) for x in self.ADMIN_USER_IDS.split(",") if x.strip()]

settings = Settings()
if not settings.GEMMA_API_KEY:
    # set fallback after instantiation so importing this module doesn't raise
    # if GEMINI_API_KEY isn't defined at class creation time
    settings.GEMMA_API_KEY = settings.GEMINI_API_KEY