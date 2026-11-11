"""Database engine, session handling and table creation."""

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def _make_engine(url: str):
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


engine = _make_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one DB session per request, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Columns added after the first release. create_all() never alters existing tables, so we add
# them here (Alembic migrations replace this when we move to AWS in stage 6).
_ADDED_COLUMNS = [
    ("documents", "uploaded_by", "VARCHAR(32)"),
    ("agent_runs", "user_id", "VARCHAR(32)"),
]


def upgrade_schema(bind) -> list[str]:
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    added: list[str] = []
    with bind.begin() as conn:
        for table, column, ddl in _ADDED_COLUMNS:
            if table not in tables:
                continue
            if column in {c["name"] for c in inspector.get_columns(table)}:
                continue
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
            added.append(f"{table}.{column}")
    return added


def init_db() -> None:
    """Create tables on startup. (Alembic migrations arrive with the auth stage.)"""
    from app import models  # noqa: F401  (registers the tables on Base)

    if engine.url.get_backend_name() == "sqlite" and engine.url.database:
        Path(engine.url.database).parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
    upgrade_schema(engine)
