"""Add reflections table

Revision ID: 0011_reflections
Revises: 0010_feedback_features
Create Date: 2026-06-22

G9 wires the reflection loop to behaviour. Each reflection cycle
(`Reflector.reflect`) persists one row: `metrics` (feedback stats + per-CPV
advisory), `actions` (the feedback-driven LR-retrain outcome + narrative source),
and a human-readable `narrative`. No FKs — it's an append-only operational log.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0011_reflections"
down_revision: str | None = "0010_feedback_features"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reflections",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("metrics", JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("actions", JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("narrative", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("reflections")
