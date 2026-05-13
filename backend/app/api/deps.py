"""Shared FastAPI dependencies (DB session, current user, etc.).

Provides a `get_db` generator yielding a SQLAlchemy session scoped to the
request lifecycle. Future deps (auth, rate limiting) will live here.
"""
from __future__ import annotations

from collections.abc import Generator
from typing import TYPE_CHECKING

from app.db.session import SessionLocal

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def get_db() -> Generator["Session", None, None]:
    """Yield a database session and ensure it is closed after use."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
