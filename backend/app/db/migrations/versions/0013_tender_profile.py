"""Add tenders.tender_profile (structured Understanding-layer output)

Revision ID: 0013_tender_profile
Revises: 0012_tender_description
Create Date: 2026-06-23

The Understanding layer (G11) extracts a structured `TenderProfile` from a
tender's title/description/dossier text via Claude (with a deterministic
fallback). This stores that JSON on the tender so the matcher can read
LLM-derived fields it cannot get from the raw columns — chiefly
`required_certifications`, which feeds the disqualifier's certification gate
(G12) — without re-running the LLM on every match. Nullable: tenders that have
not been run through extraction yet leave it NULL and the matcher falls back to
the column-only behaviour.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_tender_profile"
down_revision: str | None = "0012_tender_description"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenders",
        sa.Column("tender_profile", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenders", "tender_profile")
