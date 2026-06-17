"""Add ML-enrichment columns to the awards table

Revision ID: 0007_award_enrichment
Revises: 0006_buyer_emails
Create Date: 2026-06-16

The awards table stored who won and for how much, but not WHAT the contract
was, HOW it was procured, WHERE the work is, or the winner's stable identity —
signals the matching ML model needs to learn "which kind of notice goes to
which company". All of these are already returned by TED's CAN search
(verified populated live on 2026-06-16); this migration adds typed columns
and the backfill re-run populates them (the ON CONFLICT upsert updates
existing rows too).

  * notice_title       — contract title, original language (multilingual e5)
  * description        — full scope text (description-proc); richest signal
  * procedure_type     — eForms code: open / restricted / neg-w-call / ...
  * nuts_code          — NUTS-3 region of place-of-performance (buyer fallback)
  * winner_identifier  — tax/registration id; stronger dedup key than name
  * winner_country     — alpha-3; domestic-vs-cross-border signal
  * contract_currency  — value is in THIS currency (TED does not convert)
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_award_enrichment"
down_revision: Union[str, None] = "0006_buyer_emails"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("awards", sa.Column("notice_title", sa.Text(), nullable=True))
    op.add_column("awards", sa.Column("description", sa.Text(), nullable=True))
    op.add_column(
        "awards", sa.Column("procedure_type", sa.String(length=32), nullable=True)
    )
    op.add_column("awards", sa.Column("nuts_code", sa.String(length=16), nullable=True))
    op.add_column(
        "awards", sa.Column("winner_identifier", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "awards", sa.Column("winner_country", sa.String(length=8), nullable=True)
    )
    op.add_column(
        "awards", sa.Column("contract_currency", sa.String(length=8), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("awards", "contract_currency")
    op.drop_column("awards", "winner_country")
    op.drop_column("awards", "winner_identifier")
    op.drop_column("awards", "nuts_code")
    op.drop_column("awards", "procedure_type")
    op.drop_column("awards", "description")
    op.drop_column("awards", "notice_title")
