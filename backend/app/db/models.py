"""SQLAlchemy ORM models for the GTM Agent.

Every table:
  - has a UUID primary key
  - has `created_at` / `updated_at` timestamps
  - uses Postgres-native types (JSONB, pgvector Vector) where appropriate
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    SMALLINT,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    false,
    func,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Tender(Base):
    __tablename__ = "tenders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ted_notice_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Procedure-level project description (TED BT-24 / description-proc), original
    # language. Added 2026-06-22 (migration 0012) so the demand side carries the
    # same descriptive text the supply side (awards) already has — feeds the
    # matcher's tender embedding text.
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    buyer_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    buyer_country: Mapped[str | None] = mapped_column(String(8), nullable=True)
    cpv_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    budget_eur: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="active", default="active"
    )
    document_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_restricted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false(), default=False
    )
    # Structured Understanding-layer output (migration 0013). A JSON copy of the
    # extracted `TenderProfile` plus a `_meta` block (source/model/validation).
    # NULL until the tender has been run through `understanding.service`. The
    # matcher reads `required_certifications` from here to drive the cert gate
    # (G11/G12); absent → the matcher keeps its column-only behaviour.
    tender_profile: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    raw_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=datetime.utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        default=datetime.utcnow,
    )

    documents: Mapped[list[Document]] = relationship(back_populates="tender")
    matches: Mapped[list[Match]] = relationship(back_populates="tender")


class Company(Base):
    """Canonical company entity, populated by award-winner resolution.

    Distinct from `company_profiles` (Phase 5 — scraped capability profiles).
    `resolution_key` is the normalised name used to dedupe variant spellings.
    """

    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # canonical_name / resolution_key are indexed but NOT unique (migration
    # 0008): when `registration_id` (tax id) disambiguates two distinct legal
    # entities that share a trading name, they may legitimately occupy two
    # rows with the same name/key. Dedup is enforced in `resolve_or_create`,
    # not by a DB constraint.
    canonical_name: Mapped[str] = mapped_column(Text, index=True, nullable=False)
    resolution_key: Mapped[str] = mapped_column(Text, index=True, nullable=False)
    # Tax / registration id from TED `winner-identifier`. Stronger dedup key
    # than name normalisation when present; NULL when TED omitted it.
    registration_id: Mapped[str | None] = mapped_column(
        String(64), index=True, nullable=True
    )
    aliases: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    country: Mapped[str | None] = mapped_column(String(8), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=datetime.utcnow,
    )


class Award(Base):
    """One row per TED Award (CAN) notice.

    Distinct publications from Contract Notices — they share only a procedure
    identifier, not a row-level FK. Winners resolve to a `companies` row.
    """

    __tablename__ = "awards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ted_notice_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    cpv_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Enrichment for ML training (migration 0007). What the contract was, how
    # it was procured, where the work is, and who won — the features the
    # matching model needs to learn "which notice goes to which company".
    # notice_title/description are original-language (multilingual e5 handles
    # cross-lang); procedure_type is the eForms code (open/restricted/...);
    # nuts_code is the place-of-performance NUTS-3 (buyer region fallback);
    # contract_currency makes contract_value_eur interpretable (TED does NOT
    # convert — the value is in this currency); winner_identifier is the tax/
    # registration id (stronger dedup key than name normalisation).
    notice_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    procedure_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    nuts_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    buyer_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    buyer_country: Mapped[str | None] = mapped_column(String(8), nullable=True)
    winner_raw_name: Mapped[str] = mapped_column(Text, nullable=False)
    winner_identifier: Mapped[str | None] = mapped_column(String(64), nullable=True)
    winner_country: Mapped[str | None] = mapped_column(String(8), nullable=True)
    winner_canonical_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("companies.id"), nullable=True, index=True
    )
    contract_value_eur: Mapped[float | None] = mapped_column(Float, nullable=True)
    contract_currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    award_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    n_offers_received: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=datetime.utcnow,
    )


class Document(Base):
    """One row per attempted-or-completed dossier download.

    `tender_id` is UNIQUE — at most one document row per tender. The
    upsert path in `dossier_downloader` keys on this constraint.

    Two boolean flags carry independent meaning:
      * `is_restricted` — this specific document URL returned 401/403.
      * `download_failed` — non-auth failure (timeout, 5xx, non-PDF body).
    """

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tender_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenders.id"), unique=True, index=True, nullable=False
    )
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    storage_path: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    is_restricted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false(), default=False
    )
    download_failed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false(), default=False
    )
    file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    downloaded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True, default=None
    )

    tender: Mapped[Tender] = relationship(back_populates="documents")


class CompanyProfile(Base, TimestampMixin):
    __tablename__ = "company_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    country: Mapped[str | None] = mapped_column(String(8), nullable=True)
    website: Mapped[str | None] = mapped_column(Text, nullable=True)
    capabilities: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    certifications: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(384), nullable=True)
    # Provenance + idempotent upsert key when a profile is derived from an
    # award-winner `companies` row (Layer 1 supplier-pool builder). NULL for
    # profiles created another way (e.g. future web scraping).
    source_company_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("companies.id"), unique=True, index=True, nullable=True
    )

    matches: Mapped[list[Match]] = relationship(back_populates="company")


class Match(Base, TimestampMixin):
    __tablename__ = "matches"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tender_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenders.id"), nullable=False, index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("company_profiles.id"), nullable=False, index=True
    )
    # Legacy 4-feature sub-scores. Kept for API/frontend/email back-compat; in the
    # v5 LR path they are rollups of the 10 features below (semantic; value;
    # country-match; best-CPV-prefix). The fixed-weight fallback populates them too.
    semantic_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    budget_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    location_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    qualification_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    # v5 feature columns (migration 0009). Nullable: rows from the legacy
    # fixed-weight path leave them NULL. `semantic_score` above doubles as v5's
    # semantic feature, so it is not repeated here.
    cpv_4digit_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    cpv_2digit_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    nuts_exact_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    nuts_country_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_in_range_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    country_match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    company_size_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    competition_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False, index=True)
    weights: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_disqualified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    tender: Mapped[Tender] = relationship(back_populates="matches")
    company: Mapped[CompanyProfile] = relationship(back_populates="matches")
    emails: Mapped[list[Email]] = relationship(back_populates="match")


class Email(Base, TimestampMixin):
    __tablename__ = "emails"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    match_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("matches.id"), nullable=False, index=True
    )
    # 'supplier' (per-match outreach to the matched company) or 'buyer'
    # (per-tender digest to the tender issuer, anchored to its top match).
    recipient_type: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="supplier", default="supplier"
    )
    tender_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tenders.id"), nullable=True, index=True
    )
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    match: Mapped[Match] = relationship(back_populates="emails")


class Feedback(Base, TimestampMixin):
    __tablename__ = "feedback"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Nullable + ON DELETE SET NULL so re-matching a tender (which deletes its
    # matches) preserves the feedback row as a durable training sample instead of
    # FK-crashing or being cascade-deleted. The `features` snapshot below keeps
    # the row usable for retraining even after its match is gone.
    match_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("matches.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    email_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("emails.id"), nullable=True
    )
    rating: Mapped[int] = mapped_column(SMALLINT, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Snapshot of the match's 10 v5 features at feedback time (NULL for feedback
    # on legacy/disqualified matches). The retrainer fits on (features, rating).
    features: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class Embedding(Base, TimestampMixin):
    """RESERVED — generic cross-model vector store (768-dim). **Not yet wired.**

    A deliberate schema reservation, not a forgotten stub: the live "hot path"
    embedding is `company_profiles.embedding` (384-dim MiniLM). This table exists
    so a second model's vectors (e.g. mpnet/e5, 768-dim) can be stored for any
    source row (`source_type` + `source_id`) without changing the hot-path column's
    dimension. No producer or consumer references it today — keep it empty until a
    cross-model embedding feature actually needs it (then add the writer/reader),
    or drop it via a migration if that direction is abandoned.
    """

    __tablename__ = "embeddings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    vector: Mapped[list[float]] = mapped_column(Vector(768), nullable=False)


class AgentRun(Base, TimestampMixin):
    """Tracks Claude agent execution sessions for the reflection loop."""
    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    steps: Mapped[list | dict | None] = mapped_column(JSONB, nullable=True)
    output: Mapped[str | None] = mapped_column(Text, nullable=True)


class AgentSession(Base, TimestampMixin):
    """A resumable agent conversation (migration 0014 / G22 hardening).

    Persists the full Anthropic message array so a run that pauses on the
    `ask_user` tool (``status='awaiting_input'``) can be resumed by
    ``POST /agent/run/{id}/continue`` with the user's choice — the
    disambiguation flow (e.g. a partial tender name matched several tenders).

    Columns:
      * `messages`  — the Anthropic conversation array (plain dicts, so it
                      round-trips through JSONB and back into `messages.create`).
      * `steps`     — tool calls made so far (drives the UI steps panel).
      * `pending`   — when awaiting input: the open `ask_user` question + the
                      `tool_use_id` it must be answered against + the options.
      * `run_state` — per-run guard counters: caged-ingest call counts and the
                      zero-match flag that gates `ingest_awards`.
    """
    __tablename__ = "agent_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    dry_run: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=true(), default=True
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="running", default="running"
    )
    messages: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    steps: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    pending: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    run_state: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class TenderReport(Base, TimestampMixin):
    """A saved agent analysis for a tender (migration 0015).

    The agent's ranked top-N + narrative is otherwise transient (it lives only in
    the streamed output). This persists it, keyed to the tender, so the user can
    come back to it. `suppliers` is a self-contained snapshot of the ranked
    matches taken at save time — it survives a later re-match (same durability
    lesson as `feedback.features`). History is kept (many rows per tender).
    """
    __tablename__ = "tender_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tender_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenders.id"), nullable=False, index=True
    )
    # Provenance: which agent session produced this report (nullable — a report
    # can be saved without an agent session, and the session may be pruned).
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_sessions.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    narrative: Mapped[str] = mapped_column(Text, nullable=False)
    suppliers: Mapped[list | None] = mapped_column(JSONB, nullable=True)


class Reflection(Base, TimestampMixin):
    """One row per reflection cycle (`Reflector.reflect`, migration 0011 / G9).

    This is the "wired to behaviour" record:
      * `metrics`   — what the cycle observed (feedback stats, run counts, and the
                      deterministic per-CPV advisory recommendation).
      * `actions`   — what it actually did, e.g. the feedback-driven LR retrain
                      outcome (which mutates the served model) + the narrative
                      source. CPV recommendations are advisory only (decision B):
                      the cycle does NOT auto-mutate `allowed_cpv_codes`.
      * `narrative` — human-readable summary (Claude when a key is configured,
                      deterministic otherwise).
    """
    __tablename__ = "reflections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    actions: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
