"""Train/serve parity (G20) — the app's feature math must equal the v5 trainer's.

`app/matching/features.py` was ported from the offline v5 trainer
(`exports_ml_pipeline.py`). They are kept as *separate* implementations on purpose
(the trainer scores one tender CPV per row and sees the real competition count; the
server scores multi-CPV live tenders and can't know a future tender's competition),
so they can't be one function — but the shared per-feature math must stay identical
or the served scores drift from what the coefficients were fitted on.

This test imports BOTH implementations and asserts they agree on a table of inputs
for every function whose signature is comparable. It needs the trainer's heavy deps
(numpy/sklearn/rapidfuzz), so like the other real-model tests it `importorskip`s and
therefore **runs locally / skips in CI** (CI installs only the lean requirements).

The three *intended* divergences are asserted explicitly at the bottom so a future
reader sees they are deliberate, not accidental drift.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.matching import features as app

# The v5 trainer lives at the repo root, not under backend/.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# The trainer imports numpy (present in CI via pgvector) plus joblib/rapidfuzz/sklearn
# (ML-only, requirements-ml.txt, absent in CI). importorskip catches that ImportError
# → skips in CI, runs locally. exc_type is required so a genuine ImportError skips
# rather than warning/erroring (pytest 9.1 default change).
v5 = pytest.importorskip("exports_ml_pipeline", exc_type=ImportError)


# ── shared feature order ────────────────────────────────────────────────────


def test_feature_names_identical() -> None:
    assert app.FEATURE_NAMES == v5.FEATURE_NAMES


# ── _norm_cpv (numeric inputs — the only ones that occur in real data) ──────


@pytest.mark.parametrize("cpv", ["45000000", "45233223-7", "72000000", "451"])
def test_norm_cpv_parity_numeric(cpv: str) -> None:
    assert app._norm_cpv(cpv) == v5._norm_cpv(cpv)


# ── cpv_features: app takes a list + returns (4,2); v5 takes one + returns (8,4,2) ──


@pytest.mark.parametrize(
    "tender_cpv,company_cpvs",
    [
        ("45233223", ["45233000"]),
        ("45215130", ["45432200"]),
        ("45000000", ["72000000"]),
        ("72000000", ["72611000", "45000000"]),
    ],
)
def test_cpv_features_parity_single_cpv(tender_cpv: str, company_cpvs: list[str]) -> None:
    _cpv8, v5_4, v5_2 = v5.cpv_features(tender_cpv, company_cpvs)
    app_4, app_2 = app.cpv_features([tender_cpv], company_cpvs)
    assert (app_4, app_2) == (v5_4, v5_2)


# ── nuts_features ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "tender_nuts,company_nuts",
    [
        ("DE21", ["DE21"]),
        ("DE21", ["DE30"]),
        ("DE21", ["FR10", "DE21"]),
        ("CZ01", ["CZ06"]),
    ],
)
def test_nuts_features_parity(tender_nuts: str, company_nuts: list[str]) -> None:
    assert app.nuts_features(tender_nuts, company_nuts) == v5.nuts_features(
        tender_nuts, company_nuts
    )


# ── value_features ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "tender_eur,median,cmin,cmax",
    [
        (100_000, 100_000, 30_000, 500_000),
        (5_000_000, 100_000, 10_000, 200_000),
        (100_000_000, 50_000, 10_000, 100_000),
        (250_000, 250_000, None, None),
    ],
)
def test_value_features_parity(
    tender_eur: float, median: float, cmin: float | None, cmax: float | None
) -> None:
    a = app.value_features(tender_eur, median, cmin, cmax)
    b = v5.value_features(tender_eur, median, cmin, cmax)
    assert a == pytest.approx(b)


# ── country / size ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "country,company_countries",
    [("DEU", ["DEU", "FRA"]), ("DEU", ["FRA"]), ("CZE", ["CZE"])],
)
def test_country_match_parity(country: str, company_countries: list[str]) -> None:
    assert app.country_match_score(country, company_countries) == v5.country_match_score(
        country, company_countries
    )


@pytest.mark.parametrize("n", [0, 1, 5, 25, 100, 1000])
def test_company_size_parity(n: int) -> None:
    assert app.company_size_score(n) == pytest.approx(v5.company_size_score(n))


# ── FX table ────────────────────────────────────────────────────────────────


def test_fx_table_identical() -> None:
    from app.matching.money import RATES_TO_EUR as app_rates

    assert app_rates == v5.RATES_TO_EUR


# ── the deliberate divergences (documented, must NOT be "fixed") ────────────


def test_intended_divergence_competition_score_is_unknown_at_serve_time() -> None:
    """v5 fits on the real offer count; the server can't know a future tender's, so
    it fills UNKNOWN. compute_features must hardcode 0.5 for competition_score."""
    computed = app.compute_features(
        semantic_score=0.5,
        tender_cpvs=["45000000"],
        tender_nuts=None,
        tender_budget_eur=None,
        tender_country=None,
        capabilities={},
    )
    assert computed["competition_score"] == app.UNKNOWN == 0.5
    # v5 does compute a real competition score at train time:
    assert v5.competition_score("3") != 0.5


def test_intended_divergence_multi_cpv_any_match() -> None:
    """The server takes any-match across a live tender's several CPVs; v5 scored one."""
    # second CPV matches at 4-digit; v5 called on that single CPV would agree.
    assert app.cpv_features(["72000000", "45233223"], ["45233000"]) == (1.0, 1.0)
