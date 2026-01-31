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

    # --- OpenRouter / OpenAI Config ---
    OPENROUTER_API_KEY: str
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    
    # Models
    LLM_MODEL_ID: str
    AUDIO_IMAGE_MODEL_ID: str
    EMBEDDING_MODEL_ID: str
    EXTRACTOR_MODEL_ID: str

    # Site Info for OpenRouter Rankings
    
    # Lifetime settings (in days)
    EPISODE_LIFETIME_DAYS: float = 2.5 * 30.0 / 30.0  # 2.5 months ~ 75 days (keep float for clarity)
    WORKING_MEMORY_LIFETIME_DAYS: int = 5

    ENCRYPTION_KEY: str = Field(..., description="Must be 32 url-safe base64-encoded bytes")  # Must be 32 url-safe base64-encoded bytes
    DATA_ENCRYPTION_KEYSET_B64: str = Field(
        ...,
        description="Base64-encoded JSON keyset for Tink AEAD (AES256_GCM by default)",
    )
    
    # Google OAuth
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str

    # Admin
    ADMIN_USER_IDS: str = ""  # Comma-separated Telegram user IDs
    
    # Monitoring
    SENTRY_DSN: str = ""
    ENABLE_METRICS: bool = False
    
    # Rate limiting
    MAX_MESSAGES_PER_MINUTE: int = 15

    REDIS_URL: str = "redis://redis:6379/0"
    # Fact cleanup
    # similarity threshold for deduplication (cosine similarity). Value in [0,1].
    FACT_CLEANUP_SIMILARITY_THRESHOLD: float = 0.95
    
    # Vector dimensions for embeddings (must match EMBEDDING_MODEL_ID output)
    VECTOR_DIM: int = 4096  # Qwen3-embedding-8b outputs 4096-dimensional vectors

    # Subscription & Limits
    TRIAL_DAYS: int = 7
    # 100 Stars is approx $2.00 (Standard Telegram pricing is ~0.02 USD per star)
    SUBSCRIPTION_PRICE_STARS: int = 100 
    
    # Technical Limit (Anti-Spam)
    LIMIT_TECHNICAL_SECONDS: int = 2  # 1 message every 2 seconds
    
    # Daily Quotas
    LIMIT_DAILY_TRIAL: int = 20      # Guest/Trial
    LIMIT_DAILY_PREMIUM: int = 200   # Subscriber
    LIMIT_DAILY_EXPIRED: int = 0     # Hard block after trial ends
    
    @property
    def admin_ids(self) -> list[int]:
        if not self.ADMIN_USER_IDS:
            return []
        return [int(x.strip()) for x in self.ADMIN_USER_IDS.split(",") if x.strip()]

settings = Settings()