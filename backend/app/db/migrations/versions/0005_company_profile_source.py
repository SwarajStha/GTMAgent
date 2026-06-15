"""Add company_profiles.source_company_id (supplier-pool provenance)

Revision ID: 0005_company_profile_source
Revises: 0004_agent_runs
Create Date: 2026-06-15

Layer 1 of the matching pipeline derives `company_profiles` rows from
award-winner `companies`. `source_company_id` links a derived profile back to
its source company and serves as the unique upsert key so re-running the
builder updates rather than duplicates. Nullable — profiles created another way
(e.g. future web scraping) leave it NULL.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_company_profile_source"
down_revision: Union[str, None] = "0004_agent_runs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "company_profiles",
        sa.Column("source_company_id", sa.Integer(), nullable=True),
    )
    op.create_unique_constraint(
        "uq_company_profiles_source_company_id",
        "company_profiles",
        ["source_company_id"],
    )
    op.create_index(
        "ix_company_profiles_source_company_id",
        "company_profiles",
        ["source_company_id"],
    )
    op.create_foreign_key(
        "fk_company_profiles_source_company_id_companies",
        "company_profiles",
        "companies",
        ["source_company_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_company_profiles_source_company_id_companies",
        "company_profiles",
        type_="foreignkey",
    )
    op.drop_index("ix_company_profiles_source_company_id", table_name="company_profiles")
    op.drop_constraint(
        "uq_company_profiles_source_company_id",
        "company_profiles",
        type_="unique",
    )
    op.drop_column("company_profiles", "source_company_id")
