from __future__ import annotations

import os
from sqlmodel import SQLModel, create_engine, Session

from .config import settings


def _sqlite_connect_args(url: str):
    if url.startswith("sqlite:"):
        return {"check_same_thread": False}
    return {}


def ensure_data_dir() -> None:
    # for sqlite files like ./data/openports.db
    if settings.DATABASE_URL.startswith("sqlite:"):
        os.makedirs("data", exist_ok=True)


engine = create_engine(settings.DATABASE_URL, echo=False, connect_args=_sqlite_connect_args(settings.DATABASE_URL))


def init_db() -> None:
    ensure_data_dir()
    SQLModel.metadata.create_all(engine)


def get_session() -> Session:
    with Session(engine) as session:
        yield session
