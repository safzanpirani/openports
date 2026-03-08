from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # API keys
    SHODAN_API_KEY: str | None = None
    CENSYS_API_ID: str | None = None
    CENSYS_API_SECRET: str | None = None
    CENSYS_API_KEY: str | None = None
    ZOOMEYE_API_KEY: str | None = None
    CENSYS_COOKIE: str | None = None
    ZOOMEYE_COOKIE: str | None = None
    TELEGRAM_BOT_TOKEN: str | None = None
    TELEGRAM_CHAT_ID: str | None = None
    SHODAN_COOKIE: str | None = None

    # Optional protection for "dangerous" endpoints like triggering scans
    ADMIN_TOKEN: str | None = None

    # Storage
    DATABASE_URL: str = "sqlite:///./data/openports.db"

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def _coerce_empty_db_url(cls, v):
        # If the user keeps DATABASE_URL empty in .env, pydantic will treat it as "" and override the default.
        # Coerce empty/whitespace back to our default sqlite url.
        if v is None:
            return "sqlite:///./data/openports.db"
        if isinstance(v, str) and not v.strip():
            return "sqlite:///./data/openports.db"
        return v

    # Scanning
    SHODAN_LIMIT: int = 200
    VERIFY_CONCURRENCY: int = 50
    HTTP_TIMEOUT_SECONDS: float = 4.0
    OLLAMA_SHOW_LIMIT: int = 30

    # Scheduler
    SCAN_INTERVAL_MINUTES: int = 0  # 0 disables periodic scans; use manual trigger


settings = Settings()
