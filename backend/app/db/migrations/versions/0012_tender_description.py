"""Add tenders.description

Revision ID: 0012_tender_description
Revises: 0011_reflections
Create Date: 2026-06-22

The contract-notice poller (Job 1) only captured `notice-title`; the procurement
description (TED BT-24 / `description-proc`) was never requested or stored, so the
demand side lacked the descriptive text the supply side (`awards.description`,
migration 0007) already has. This adds `tenders.description` (TEXT, original
language); the poller now requests `description-proc` and the matcher folds it
into the tender embedding text (aligning serve-time text with v5's training).
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_tender_description"
down_revision: str | None = "0011_reflections"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tenders", sa.Column("description", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("tenders", "description")
