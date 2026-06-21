"""Add v5 LR feature columns to the matches table

Revision ID: 0009_match_v5_features
Revises: 0008_company_registration_id
Create Date: 2026-06-21

Step 4 ports the standalone v5 matcher (exports_ml_pipeline.py) into
app/matching. The v5 Logistic Regression ranks on 10 features; the matches table
only had the legacy 4 sub-scores. This adds the 9 v5 feature columns that aren't
already represented (v5's `semantic_score` reuses the existing column). All are
nullable Float: existing rows + the legacy fixed-weight fallback path leave them
NULL; the v5 path populates them. The legacy `budget_score`/`location_score`/
`qualification_score` columns are kept as back-compat rollups (see models.py).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_match_v5_features"
down_revision: Union[str, None] = "0008_company_registration_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FEATURE_COLUMNS = (
    "cpv_4digit_score",
    "cpv_2digit_score",
    "nuts_exact_score",
    "nuts_country_score",
    "value_score",
    "value_in_range_score",
    "country_match_score",
    "company_size_score",
    "competition_score",
)


def upgrade() -> None:
    for name in _FEATURE_COLUMNS:
        op.add_column("matches", sa.Column(name, sa.Float(), nullable=True))


def downgrade() -> None:
    for name in reversed(_FEATURE_COLUMNS):
        op.drop_column("matches", name)
