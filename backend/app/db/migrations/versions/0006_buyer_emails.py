"""Add buyer-facing email support to the emails table

Revision ID: 0006_buyer_emails
Revises: 0005_company_profile_source
Create Date: 2026-06-16

Two-sided outreach: supplier emails are per-match (one supplier), buyer emails
are per-tender (a digest of the tender's top matches). We add:
  * `recipient_type` ('supplier' | 'buyer', default 'supplier')
  * `tender_id` (nullable FK) so a buyer email can be found by tender.

`match_id` stays NOT NULL; a buyer email anchors it to the tender's top match
(the top-N list lives in `evidence`), avoiding a nullable-FK migration (D3).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_buyer_emails"
down_revision: Union[str, None] = "0005_company_profile_source"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "emails",
        sa.Column(
            "recipient_type",
            sa.String(length=16),
            nullable=False,
            server_default="supplier",
        ),
    )
    op.add_column(
        "emails",
        sa.Column("tender_id", sa.Integer(), nullable=True),
    )
    op.create_index("ix_emails_tender_id", "emails", ["tender_id"])
    op.create_foreign_key(
        "fk_emails_tender_id_tenders",
        "emails",
        "tenders",
        ["tender_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_emails_tender_id_tenders", "emails", type_="foreignkey")
    op.drop_index("ix_emails_tender_id", table_name="emails")
    op.drop_column("emails", "tender_id")
    op.drop_column("emails", "recipient_type")
