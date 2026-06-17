"""Add companies.registration_id; relax name/key uniqueness for ID-based dedup

Revision ID: 0008_company_registration_id
Revises: 0007_award_enrichment
Create Date: 2026-06-16

Entity resolution gains a stronger key: the winner's tax/registration id
(TED `winner-identifier`). `resolve_or_create` now matches on it first,
which (a) merges variant spellings of the same legal entity that share an id
and (b) splits two distinct entities that happen to normalise to the same
trading name. Case (b) means two rows may legitimately share a
`canonical_name` / `resolution_key`, so their unique indexes are relaxed to
plain indexes — dedup is enforced in code, the PK is the only hard unique.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_company_registration_id"
down_revision: Union[str, None] = "0007_award_enrichment"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "companies", sa.Column("registration_id", sa.String(length=64), nullable=True)
    )
    op.create_index(
        "ix_companies_registration_id", "companies", ["registration_id"]
    )
    # Relax unique -> plain index on both name columns.
    op.drop_index("ix_companies_resolution_key", table_name="companies")
    op.create_index("ix_companies_resolution_key", "companies", ["resolution_key"])
    op.drop_index("ix_companies_canonical_name", table_name="companies")
    op.create_index("ix_companies_canonical_name", "companies", ["canonical_name"])


def downgrade() -> None:
    op.drop_index("ix_companies_canonical_name", table_name="companies")
    op.create_index(
        "ix_companies_canonical_name", "companies", ["canonical_name"], unique=True
    )
    op.drop_index("ix_companies_resolution_key", table_name="companies")
    op.create_index(
        "ix_companies_resolution_key", "companies", ["resolution_key"], unique=True
    )
    op.drop_index("ix_companies_registration_id", table_name="companies")
    op.drop_column("companies", "registration_id")
