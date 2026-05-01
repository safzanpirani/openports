from __future__ import annotations

from pathlib import Path

from sqlmodel import SQLModel, create_engine, Session

from .config import settings


def _sqlite_connect_args(url: str):
    if url.startswith("sqlite:"):
        return {"check_same_thread": False}
    return {}


def _sqlite_file_path(url: str) -> Path | None:
    if url == "sqlite:///:memory:" or not url.startswith("sqlite:"):
        return None
    if url.startswith("sqlite:////"):
        return Path(url.removeprefix("sqlite:///"))
    if url.startswith("sqlite:///"):
        return Path(url.removeprefix("sqlite:///"))
    if url.startswith("sqlite://"):
        return Path(url.removeprefix("sqlite://"))
    return None


def ensure_data_dir() -> None:
    db_path = _sqlite_file_path(settings.DATABASE_URL)
    if db_path is None:
        return
    db_path.parent.mkdir(parents=True, exist_ok=True)


engine = create_engine(
    settings.DATABASE_URL,
    echo=False,
    connect_args=_sqlite_connect_args(settings.DATABASE_URL),
)


def init_db() -> None:
    ensure_data_dir()
    SQLModel.metadata.create_all(engine)


def get_session() -> Session:
    with Session(engine) as session:
        yield session
