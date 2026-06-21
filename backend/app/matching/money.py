"""Currency normalisation for the matcher (G7).

TED contract values are **not** EUR-converted — each is denominated in its own
`contract_currency` — and TED uses ``-1``/``0`` as "not disclosed" sentinels.
Comparing a tender budget against a company's historical values (or feeding them
to the value features) therefore requires converting both sides to EUR and
dropping sentinels first.

The FX table mirrors the v5 trainer's `RATES_TO_EUR` (`exports_ml_pipeline.py`)
so the in-app value features match the EUR scale the LR was trained on. It is a
deliberate copy (the trainer is a standalone root script that can't be imported
without side effects) — keep the two tables in sync (gap G20).
"""
from __future__ import annotations

# Approximate EUR conversion rates (mirror of v5's RATES_TO_EUR).
RATES_TO_EUR: dict[str, float] = {
    "EUR": 1.0, "PLN": 0.23, "CZK": 0.040, "HUF": 0.0026, "RON": 0.20,
    "BGN": 0.51, "HRK": 0.133, "DKK": 0.134, "SEK": 0.088, "NOK": 0.087,
    "CHF": 1.06, "GBP": 1.17, "USD": 0.92, "TRY": 0.028, "RSD": 0.0085,
    "MKD": 0.0163, "ALL": 0.0105,
}


def to_eur(value: float | str | None, currency: str | None) -> float | None:
    """Convert `value` (in `currency`) to EUR, or return None if not usable.

    None is returned for a missing/non-numeric value, a non-positive sentinel
    (``-1``/``0``), or an unknown/blank currency — callers treat None as
    "no usable amount" (the value features then fall back to their 0.5 fill).
    """
    try:
        v = float(value)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return None
    if v <= 0:
        return None
    rate = RATES_TO_EUR.get((currency or "").strip().upper())
    return v * rate if rate else None
