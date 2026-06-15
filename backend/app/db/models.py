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

    documents: Mapped[list["Document"]] = relationship(back_populates="tender")
    matches: Mapped[list["Match"]] = relationship(back_populates="tender")


class Company(Base):
    """Canonical company entity, populated by award-winner resolution.

    Distinct from `company_profiles` (Phase 5 — scraped capability profiles).
    `resolution_key` is the normalised name used to dedupe variant spellings.
    """

    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    canonical_name: Mapped[str] = mapped_column(Text, unique=True, index=True, nullable=False)
    resolution_key: Mapped[str] = mapped_column(Text, unique=True, index=True, nullable=False)
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
    buyer_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    buyer_country: Mapped[str | None] = mapped_column(String(8), nullable=True)
    winner_raw_name: Mapped[str] = mapped_column(Text, nullable=False)
    winner_canonical_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("companies.id"), nullable=True, index=True
    )
    contract_value_eur: Mapped[float | None] = mapped_column(Float, nullable=True)
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

    matches: Mapped[list["Match"]] = relationship(back_populates="company")


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
    semantic_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    budget_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    location_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    qualification_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    final_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False, index=True)
    weights: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_disqualified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    tender: Mapped[Tender] = relationship(back_populates="matches")
    company: Mapped[CompanyProfile] = relationship(back_populates="matches")
    emails: Mapped[list["Email"]] = relationship(back_populates="match")


class Email(Base, TimestampMixin):
    __tablename__ = "emails"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    match_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("matches.id"), nullable=False, index=True
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
    match_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("matches.id"), nullable=False, index=True
    )
    email_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("emails.id"), nullable=True
    )
    rating: Mapped[int] = mapped_column(SMALLINT, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)


class Embedding(Base, TimestampMixin):
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
