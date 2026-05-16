"""Initial schema with pgvector.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-05-13

Creates the pgvector extension and all eight core tables.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "tenders",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("ted_notice_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("title", sa.Text, nullable=True),
        sa.Column("buyer_name", sa.Text, nullable=True),
        sa.Column("buyer_country", sa.String(8), nullable=True),
        sa.Column("cpv_codes", JSONB, nullable=False),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("budget_eur", sa.Float, nullable=True),
        sa.Column("currency", sa.String(8), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("document_url", sa.Text, nullable=True),
        sa.Column("is_restricted", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("raw_json", JSONB, nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "awards",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tender_id", sa.Integer, sa.ForeignKey("tenders.id"), nullable=False, index=True),
        sa.Column("winner_name", sa.Text, nullable=False),
        sa.Column("winner_country", sa.String(8), nullable=True),
        sa.Column("contract_value_eur", sa.Float, nullable=True),
        sa.Column("award_date", sa.Date, nullable=True),
        sa.Column("cpv_code", sa.String(32), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tender_id", sa.Integer, sa.ForeignKey("tenders.id"), nullable=False, index=True),
        sa.Column("filename", sa.Text, nullable=False),
        sa.Column("storage_path", sa.Text, nullable=False),
        sa.Column("is_restricted", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("text_content", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "company_profiles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text, nullable=False, index=True),
        sa.Column("country", sa.String(8), nullable=True),
        sa.Column("website", sa.Text, nullable=True),
        sa.Column("capabilities", JSONB, nullable=True),
        sa.Column("certifications", JSONB, nullable=True),
        sa.Column("embedding", Vector(384), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "matches",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tender_id", sa.Integer, sa.ForeignKey("tenders.id"), nullable=False, index=True),
        sa.Column("company_id", UUID(as_uuid=True), sa.ForeignKey("company_profiles.id"), nullable=False, index=True),
        sa.Column("semantic_score", sa.Float, nullable=False, server_default="0"),
        sa.Column("budget_score", sa.Float, nullable=False, server_default="0"),
        sa.Column("location_score", sa.Float, nullable=False, server_default="0"),
        sa.Column("qualification_score", sa.Float, nullable=False, server_default="0"),
        sa.Column("final_score", sa.Float, nullable=False, server_default="0", index=True),
        sa.Column("weights", JSONB, nullable=True),
        sa.Column("explanation", sa.Text, nullable=True),
        sa.Column("is_disqualified", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "emails",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("match_id", UUID(as_uuid=True), sa.ForeignKey("matches.id"), nullable=False, index=True),
        sa.Column("subject", sa.Text, nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("evidence", JSONB, nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "feedback",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("match_id", UUID(as_uuid=True), sa.ForeignKey("matches.id"), nullable=False, index=True),
        sa.Column("email_id", UUID(as_uuid=True), sa.ForeignKey("emails.id"), nullable=True),
        sa.Column("rating", sa.SmallInteger, nullable=False),
        sa.Column("comment", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "embeddings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("source_type", sa.String(32), nullable=False, index=True),
        sa.Column("source_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("model_name", sa.String(64), nullable=False),
        sa.Column("vector", Vector(768), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("embeddings")
    op.drop_table("feedback")
    op.drop_table("emails")
    op.drop_table("matches")
    op.drop_table("company_profiles")
    op.drop_table("documents")
    op.drop_table("awards")
    op.drop_table("tenders")
    op.execute("DROP EXTENSION IF EXISTS vector")
