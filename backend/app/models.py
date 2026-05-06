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

    # Hosting / provider classification
    provider: str | None = Field(default=None, index=True)
    reverse_dns: str | None = Field(default=None)

    # Raw data
    shodan: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    service_metadata: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    models: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))

    # Derived convenience fields (best-effort)
    title: str | None = Field(default=None)
    version: str | None = Field(default=None)
    gpu_name: str | None = Field(default=None)
    vram_total_gb: float | None = Field(default=None)
    vram_free_gb: float | None = Field(default=None)
    ram_total_gb: float | None = Field(default=None)
    ram_free_gb: float | None = Field(default=None)
    model_count: int | None = Field(default=None)
    max_model_params: float | None = Field(default=None)
    max_context: int | None = Field(default=None)
    node_count: int | None = Field(default=None)

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


class InstanceCheck(SQLModel, table=True):
    """One row per fingerprint attempt. Lightweight history of an instance."""

    id: Optional[int] = Field(default=None, primary_key=True)
    instance_id: int = Field(foreign_key="instance.id", index=True)
    checked_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    is_alive: bool
    version: str | None = Field(default=None)
    gpu_name: str | None = Field(default=None)
    vram_total_gb: float | None = Field(default=None)
    vram_free_gb: float | None = Field(default=None)
    model_count: int | None = Field(default=None)
    max_model_params: float | None = Field(default=None)
    max_context: int | None = Field(default=None)
    error: str | None = Field(default=None)


class InstanceChange(SQLModel, table=True):
    """One row per detected change between consecutive fingerprints.

    `kind` is one of: `alive_changed`, `version_changed`, `models_changed`,
    `gpu_changed`, `first_seen`. `before`/`after` carry the relevant context
    in JSON shape (e.g. `{added: [...], removed: [...]}` for models).
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    instance_id: int = Field(foreign_key="instance.id", index=True)
    at: datetime = Field(default_factory=datetime.utcnow, index=True)
    kind: str = Field(index=True)
    before: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    after: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
