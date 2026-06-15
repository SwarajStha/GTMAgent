"""Hard disqualifier gates.

A company is removed from consideration for a tender *before* scoring if it
fails any hard gate. Gates are conservative on purpose — soft mismatches
(wrong region, weak budget fit) belong in the [0, 1] sub-scores, not here.

Pure and dependency-free: operates on primitives so the pipeline can extract
the relevant fields from ORM objects and call this directly.
"""
from __future__ import annotations


class Disqualifier:
    """Applies hard disqualification gates to a (tender, company) pair."""

    # A tender whose budget exceeds the company's max deal size by more than
    # this factor is treated as beyond the company's delivery capacity.
    HARD_BUDGET_MULTIPLE = 10.0

    def check(
        self,
        *,
        tender_budget_eur: float | None = None,
        required_certifications: list[str] | None = None,
        company_certifications: list[str] | None = None,
        deal_max: float | None = None,
    ) -> tuple[bool, list[str]]:
        """Return ``(is_disqualified, reasons)``.

        Gates:
          * a mandatory certification the tender requires is not held;
          * the tender budget far exceeds the company's delivery capacity.
        """
        reasons: list[str] = []

        required = {c.strip().lower() for c in (required_certifications or []) if c.strip()}
        held = {c.strip().lower() for c in (company_certifications or []) if c.strip()}
        missing = required - held
        if required and missing:
            reasons.append(f"missing required certification(s): {sorted(missing)}")

        if (
            tender_budget_eur is not None
            and deal_max is not None
            and deal_max > 0
            and tender_budget_eur > deal_max * self.HARD_BUDGET_MULTIPLE
        ):
            reasons.append("tender budget far exceeds company delivery capacity")

        return (len(reasons) > 0, reasons)
