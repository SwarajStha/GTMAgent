"""Add tender_reports (saved agent analyses per tender)

Revision ID: 0015_tender_reports
Revises: 0014_agent_sessions
Create Date: 2026-06-30

The agent's ranked top-N + narrative is otherwise transient (streamed output
only). This table persists a saved analysis keyed to a tender, with a
self-contained `suppliers` snapshot of the ranked matches at save time (survives
a later re-match). History is kept — many reports per tender.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_tender_reports"
down_revision: str | None = "0014_agent_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tender_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tender_id",
            sa.Integer(),
            sa.ForeignKey("tenders.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_sessions.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("goal", sa.Text(), nullable=True),
        sa.Column("narrative", sa.Text(), nullable=False),
        sa.Column("suppliers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
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


def downgrade() -> None:
    op.drop_table("tender_reports")
