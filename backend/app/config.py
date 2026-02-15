from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # API keys
    SHODAN_API_KEY: str | None = None
    TELEGRAM_BOT_TOKEN: str | None = None
    TELEGRAM_CHAT_ID: str | None = None

    # Optional protection for "dangerous" endpoints like triggering scans
    ADMIN_TOKEN: str | None = None

    # Storage
    DATABASE_URL: str = "sqlite:///./data/openports.db"

    # Scanning
    SHODAN_LIMIT: int = 200
    VERIFY_CONCURRENCY: int = 50
    HTTP_TIMEOUT_SECONDS: float = 4.0
    OLLAMA_SHOW_LIMIT: int = 30

    # Scheduler
    SCAN_INTERVAL_MINUTES: int = 0  # 0 disables periodic scans; use manual trigger


settings = Settings()
