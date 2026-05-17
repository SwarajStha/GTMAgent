"""Job 3: drop scaffold documents, add Job-3 documents shape.

Revision ID: 0003_add_documents
Revises: 0002_awards_companies
Create Date: 2026-05-17

The scaffold `documents` table from 0001 (UUID PK, filename/storage_path
NOT NULL, text_content) is replaced with the Job-3 shape:
  * int PK + UNIQUE FK to tenders (one document per tender)
  * source_url (the URL we tried), storage_path (nullable until a
    successful download), extracted_text (PyMuPDF output, nullable),
    file_hash (sha256 of PDF body, dedup key), downloaded_at
  * is_restricted + download_failed booleans for the two distinct
    failure modes (auth wall vs. transport/format error)

The scaffold has no rows (Job 1+2 didn't touch it), so DROP TABLE is
data-safe. The existing tenders/awards/companies tables and their
ingested rows are untouched.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0003_add_documents"
down_revision: Union[str, None] = "0002_awards_companies"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("documents")

    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "tender_id",
            sa.Integer(),
            sa.ForeignKey("tenders.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=True),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column(
            "is_restricted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "download_failed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("file_hash", sa.String(64), nullable=True),
        sa.Column("downloaded_at", sa.DateTime(timezone=False), nullable=True),
    )
    op.create_unique_constraint(
        "uq_documents_tender_id", "documents", ["tender_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_documents_tender_id", "documents", type_="unique")
    op.drop_table("documents")

    # Restore the 0001 scaffold shape so the migration history is reversible.
    op.create_table(
        "documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tender_id",
            sa.Integer(),
            sa.ForeignKey("tenders.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column(
            "is_restricted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("text_content", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
