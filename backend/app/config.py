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
    NETLAS_API_KEY: str | None = None
    CENSYS_COOKIE: str | None = None
    ZOOMEYE_COOKIE: str | None = None
    TELEGRAM_BOT_TOKEN: str | None = None
    TELEGRAM_CHAT_ID: str | None = None
    SHODAN_COOKIE: str | None = None

    # Optional protection for "dangerous" endpoints like triggering scans
    ADMIN_TOKEN: str | None = None

    # HTTP
    # Comma-separated list, e.g. "http://localhost:5173,https://openports.example.com".
    # "*" is convenient for local/dev deployments, but do not combine it with credentials.
    CORS_ORIGINS: str = "*"

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

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    # Scanning
    SHODAN_LIMIT: int = 200
    VERIFY_CONCURRENCY: int = 50
    HTTP_TIMEOUT_SECONDS: float = 4.0
    OLLAMA_SHOW_LIMIT: int = 30
    # Hard ceiling on how long a single (ip, port) fingerprint may run, across
    # all its sub-requests. httpx's timeout is per socket-operation, so a host
    # that drip-feeds bytes can pin a verify (and its concurrency slot) forever
    # — which is what made full scans run for hours. wait_for enforces a total.
    VERIFY_DEADLINE_SECONDS: float = 45.0

    # Scheduler
    # 0 disables that loop; use manual trigger.
    SCAN_INTERVAL_MINUTES: int = 0
    RECHECK_INTERVAL_MINUTES: int = 0
    # Only re-fingerprint instances whose last_checked_at is older than this many minutes.
    RECHECK_STALE_AFTER_MINUTES: int = 60
    # Cap concurrent re-fingerprints (uses HTTP, so be polite).
    RECHECK_CONCURRENCY: int = 25
    # Which sources the scheduled scan queries. Comma-separated subset of
    # shodan,censys,zoomeye,netlas. Blank/None = "all enabled" (recommended —
    # the cron stays useful even if one source's credits run out).
    SCAN_SOURCES: str | None = None
    # How long a scheduler tick may be delayed before APScheduler treats it as
    # "missed" and skips it. APScheduler's 1s default silently drops ticks
    # whenever the event loop is briefly busy, which is the usual reason a cron
    # "runs inconsistently". Keep this generous.
    SCHEDULER_MISFIRE_GRACE_SECONDS: int = 300

    @property
    def scan_sources_list(self) -> list[str] | None:
        if not self.SCAN_SOURCES or not self.SCAN_SOURCES.strip():
            return None
        return [s.strip().lower() for s in self.SCAN_SOURCES.split(",") if s.strip()]


settings = Settings()
