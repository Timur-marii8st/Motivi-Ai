from pydantic_settings import BaseSettings, SettingsConfigDict

class MCPSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra='ignore')

    MCP_SECRET_TOKEN: str  # Shared secret for auth
    TELEGRAM_BOT_TOKEN: str  # For sending files/pinning
    
    LOG_LEVEL: str = "INFO"
    TEMP_FILES_DIR: str = "/tmp/motivi_files"

mcp_settings = MCPSettings()