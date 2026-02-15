from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


class Service(str, Enum):
    comfyui = "comfyui"
    ollama = "ollama"


class Instance(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    service: Service = Field(index=True)
    ip: str = Field(index=True)
    port: int = Field(index=True)

    first_seen_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    last_seen_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    last_checked_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    is_alive: bool = Field(default=True, index=True)

    # Raw data
    shodan: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    service_metadata: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    models: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))

    # Derived convenience fields (best-effort)
    title: str | None = Field(default=None)
    version: str | None = Field(default=None)
    gpu_name: str | None = Field(default=None)

    last_error: str | None = Field(default=None)


class ScanRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    source: str = Field(index=True)  # e.g. "shodan"
    query: str | None = Field(default=None)

    started_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    finished_at: datetime | None = Field(default=None, index=True)

    candidates: int = 0
    verified: int = 0
    new_instances: int = 0

    error: str | None = Field(default=None)
