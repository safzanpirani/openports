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
    # Import models so they register with SQLModel.metadata
    from . import models as _models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    _apply_lightweight_migrations()


def _apply_lightweight_migrations() -> None:
    """Add columns added after the table was first created.

    SQLAlchemy's `create_all` only creates missing tables; it doesn't ALTER
    existing ones. We do explicit additive migrations here for SQLite to
    avoid pulling in alembic for a single-table app.
    """
    from sqlalchemy import inspect, text

    # Each entry: (table, column, ddl-fragment)
    migrations: list[tuple[str, str, str]] = [
        ("instance", "discovery_sources", "ALTER TABLE instance ADD COLUMN discovery_sources JSON"),
    ]

    insp = inspect(engine)
    if "instance" not in insp.get_table_names():
        return

    existing = {c["name"] for c in insp.get_columns("instance")}
    with engine.begin() as conn:
        for table, col, ddl in migrations:
            if table != "instance":
                continue
            if col in existing:
                continue
            try:
                conn.execute(text(ddl))
                existing.add(col)
            except Exception:
                # Column probably already exists or sqlite is unhappy; skip silently.
                pass


def get_session() -> Session:
    with Session(engine) as session:
        yield session
