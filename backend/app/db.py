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
    """Add columns SQLModel knows about that SQLite doesn't have yet.

    SQLAlchemy's `create_all` only creates missing tables; it doesn't ALTER
    existing ones. We diff the live schema against `SQLModel.metadata` and
    issue `ALTER TABLE … ADD COLUMN` for any newcomers. SQLite-specific.
    """
    import logging
    from sqlalchemy import inspect, text
    from sqlmodel import SQLModel

    log = logging.getLogger("openports.migrate")
    insp = inspect(engine)
    live_tables = set(insp.get_table_names())

    with engine.begin() as conn:
        for table_name, table in SQLModel.metadata.tables.items():
            if table_name not in live_tables:
                # `create_all` will (or did) create it; nothing to migrate.
                continue
            existing = {c["name"] for c in insp.get_columns(table_name)}
            for col in table.columns:
                if col.name in existing:
                    continue
                # Best-effort SQLite-friendly type rendering.
                try:
                    col_type = col.type.compile(dialect=engine.dialect)
                except Exception:
                    col_type = "JSON"
                ddl = f'ALTER TABLE "{table_name}" ADD COLUMN "{col.name}" {col_type}'
                try:
                    conn.execute(text(ddl))
                    log.info("migrated: added %s.%s", table_name, col.name)
                except Exception as e:
                    log.warning("migrate %s.%s failed: %s", table_name, col.name, e)


def get_session() -> Session:
    with Session(engine) as session:
        yield session
