"""SQLAlchemy engine and session factory.

Uses the *pooled* connection string (DATABASE_URL, port 6543) for runtime
queries. Alembic uses the *direct* string (DATABASE_URL_DIRECT, 5432).
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

_settings = get_settings()

engine = create_engine(
    _settings.database_url,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)

# Separate engine for the agent's `query_db` tool, bound to a least-privilege
# read-only role (P2 structural fix). Lazily built + cached so it is created only
# when DATABASE_URL_READONLY is configured (prod hardening); left None in
# dev/CI/tests, where query_db falls back to the guarded shared session.
_readonly_engine = None
_readonly_engine_ready = False


def get_readonly_engine():
    """Return the cached least-privilege read-only engine, or None if
    DATABASE_URL_READONLY is not configured. See app/agent/tools.py:query_db."""
    global _readonly_engine, _readonly_engine_ready
    if not _readonly_engine_ready:
        url = get_settings().database_url_readonly
        _readonly_engine = (
            create_engine(url, pool_pre_ping=True, pool_size=2, future=True)
            if url
            else None
        )
        _readonly_engine_ready = True
    return _readonly_engine


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


@contextmanager
def get_session() -> Iterator[Session]:
    """Yield a Session, commit on success, rollback + re-raise on error."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
