"""Shared pytest fixtures, scoped to all tests under `backend/tests/`.

Two distinct concerns live here:

  * `client` — FastAPI TestClient for HTTP-level tests (test_health.py).
  * `db_engine` + `db_session` — real Postgres session for DB-touching
    tests, with full per-test rollback isolation. Connects to a separate
    test database identified by `Settings.database_url_test` (default
    `gtm_test` on the same Docker container as the dev DB). One-time
    setup is documented in `backend/scripts/README.md` (test DB section).

`db_session` uses SQLAlchemy 2's "join an external transaction" pattern:

    * A single outer transaction is opened on a shared Connection.
    * All sessions (including those production code creates via
      `get_session()`) are bound to the same Connection in
      `join_transaction_mode="create_savepoint"`. Internal `commit()`
      calls become savepoint releases, not real commits.
    * On teardown, the outer transaction is rolled back, which undoes
      every savepoint inside it — zero per-test cleanup needed.

If `DATABASE_URL_TEST` is unreachable (e.g. CI without a Postgres
service), the DB fixtures will fail at session scope with a clear error.
Tests that don't request a DB fixture (unit tests on pure helpers) are
unaffected.
"""
from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

import app.db.models  # noqa: F401 — register all ORM models on Base.metadata
from app.core.config import get_settings
from app.db import session as session_module
from app.db.session import Base
from app.main import app


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def _offline_email_drafter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the LLM email drafter offline across the whole suite, even when a real
    ANTHROPIC_API_KEY is present in `.env` — forces the deterministic fallback
    path. Tests that exercise the Claude path inject a fake client into
    `EmailDrafter`, which bypasses this gate (the gate only applies when no client
    was supplied)."""
    import app.generation.drafter as drafter

    monkeypatch.setattr(drafter, "_llm_available", lambda: False)


@pytest.fixture(autouse=True)
def _offline_extractor(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the Understanding-layer field extractor offline across the suite
    (deterministic fallback), even with a real ANTHROPIC_API_KEY in `.env`. Tests
    that exercise the Claude path inject a fake client into `FieldExtractor`,
    which bypasses this gate (the gate only applies when no client was supplied)."""
    import app.understanding.extractor as extractor

    monkeypatch.setattr(extractor, "_llm_available", lambda: False)


@pytest.fixture(autouse=True)
def _offline_reflector(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the reflection-loop narrative offline across the suite (deterministic
    path), even with a real ANTHROPIC_API_KEY in `.env`. Tests that exercise the
    Claude narrative inject a fake client into `Reflector`, which bypasses this
    gate (the gate only applies when no client was supplied)."""
    import app.agent.reflector as reflector

    monkeypatch.setattr(reflector, "_llm_available", lambda: False)


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    """Create + drop the schema on the test database once per session."""
    url = get_settings().database_url_test
    engine = create_engine(url, future=True)

    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()

    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def db_session(
    db_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Session]:
    """Per-test session with full rollback isolation.

    Patches `app.db.session.SessionLocal` so that production code calling
    `get_session()` joins this connection's transaction via a savepoint.
    """
    connection = db_engine.connect()
    transaction = connection.begin()

    TestingSession = sessionmaker(
        bind=connection,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    monkeypatch.setattr(session_module, "engine", db_engine)
    monkeypatch.setattr(session_module, "SessionLocal", TestingSession)

    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
