"""Add feedback feature snapshot + make match_id durable across re-matches

Revision ID: 0010_feedback_features
Revises: 0009_match_v5_features
Create Date: 2026-06-21

Step 5 (G8) wires the feedback → LR-retraining loop. For feedback to survive a
tender being re-matched (which deletes + reinserts its `matches`), two changes:

  * `feedback.features` (JSONB) — snapshot of the match's 10 v5 features at
    feedback time, so the (features, rating) training pair stays usable even
    after the underlying match row is gone.
  * `feedback.match_id` → nullable + ON DELETE SET NULL — deleting a match now
    nulls the reference instead of FK-crashing (same class of bug as G26's
    emails fix) or cascade-deleting the training signal.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_feedback_features"
down_revision: str | None = "0009_match_v5_features"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FK = "feedback_match_id_fkey"


def upgrade() -> None:
    op.add_column("feedback", sa.Column("features", postgresql.JSONB(), nullable=True))
    op.drop_constraint(_FK, "feedback", type_="foreignkey")
    op.alter_column(
        "feedback", "match_id", existing_type=postgresql.UUID(), nullable=True
    )
    op.create_foreign_key(
        _FK, "feedback", "matches", ["match_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    op.drop_constraint(_FK, "feedback", type_="foreignkey")
    op.alter_column(
        "feedback", "match_id", existing_type=postgresql.UUID(), nullable=False
    )
    op.create_foreign_key(_FK, "feedback", "matches", ["match_id"], ["id"])
    op.drop_column("feedback", "features")
