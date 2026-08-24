"""SQLAlchemy engine and request-scoped session lifecycle."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from proofpay.config import get_settings


def _enable_sqlite_foreign_keys(dbapi_connection: object, _: object) -> None:
    """Enable SQLite foreign-key enforcement for every pooled connection."""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def build_engine(database_url: str | None = None) -> Engine:
    """Build an engine for the configured SQLite or PostgreSQL database."""
    url = database_url or get_settings().database_url
    parsed_url = make_url(url)
    is_sqlite = parsed_url.get_backend_name() == "sqlite"
    is_memory_sqlite = is_sqlite and parsed_url.database in {None, "", ":memory:"}

    engine_options: dict[str, object] = {"pool_pre_ping": True}
    if is_sqlite:
        engine_options["connect_args"] = {
            "check_same_thread": False,
            "timeout": 30.0,
        }
    if is_memory_sqlite:
        engine_options["poolclass"] = StaticPool

    engine = create_engine(url, **engine_options)
    if is_sqlite:
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


engine = build_engine()
SessionFactory = sessionmaker(
    bind=engine,
    class_=Session,
    autoflush=False,
    expire_on_commit=False,
)


def get_session() -> Generator[Session, None, None]:
    """Yield one session for a request and close it after the request ends."""
    with SessionFactory() as session:
        yield session
