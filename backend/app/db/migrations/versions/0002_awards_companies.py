"""Job 2: replace scaffold awards with the back-fill shape; add companies.

Revision ID: 0002_awards_companies
Revises: 0001_initial_schema
Create Date: 2026-05-16

The scaffold `awards` table from 0001 had a UUID PK and a tender_id FK.
Job 2 changes both:
  - Awards are NOT children of tenders. A TED Award (CAN) notice is a
    separate publication from its Contract Notice — they share only the
    procedure identifier, not a row-level relationship.
  - Awards instead reference a new `companies` table that canonicalises
    winner names (variant spellings of the same legal entity dedupe to
    one row via a normalised resolution_key).

The 0001 awards table is dropped and recreated rather than altered —
much simpler, and there is no production award data to preserve.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0002_awards_companies"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("awards")

    op.create_table(
        "companies",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("canonical_name", sa.Text, nullable=False, unique=True, index=True),
        sa.Column("resolution_key", sa.Text, nullable=False, unique=True, index=True),
        sa.Column("aliases", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("country", sa.String(8), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "awards",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "ted_notice_id", sa.String(64), nullable=False, unique=True, index=True
        ),
        sa.Column("cpv_code", sa.String(32), nullable=True),
        sa.Column("buyer_name", sa.Text, nullable=True),
        sa.Column("buyer_country", sa.String(8), nullable=True),
        sa.Column("winner_raw_name", sa.Text, nullable=False),
        sa.Column(
            "winner_canonical_id",
            sa.Integer,
            sa.ForeignKey("companies.id"),
            nullable=True,
            index=True,
        ),
        sa.Column("contract_value_eur", sa.Float, nullable=True),
        sa.Column("award_date", sa.Date, nullable=True),
        sa.Column("n_offers_received", sa.Integer, nullable=True),
        sa.Column("raw_json", sa.JSON, nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("awards")
    op.drop_table("companies")

    # Re-create the original scaffold awards table from 0001.
    op.create_table(
        "awards",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tender_id",
            sa.Integer,
            sa.ForeignKey("tenders.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("winner_name", sa.Text, nullable=False),
        sa.Column("winner_country", sa.String(8), nullable=True),
        sa.Column("contract_value_eur", sa.Float, nullable=True),
        sa.Column("award_date", sa.Date, nullable=True),
        sa.Column("cpv_code", sa.String(32), nullable=False, index=True),
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
