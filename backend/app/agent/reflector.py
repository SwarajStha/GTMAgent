"""Reflection loop — turns recent activity into behaviour (G9).

Two things make this more than narration:

  * **Weights (automatic).** When enough labelled feedback has accrued, the cycle
    calls `FeedbackRetrainer.retrain()`, which writes `model_params_feedback.json`
    — the file the matching pipeline auto-serves in preference to the v5 base
    (delete it to revert). So thumbs-up/down feedback actually moves the served
    model, on a cadence.
  * **CPV filters (advisory — decision B).** The cycle computes a deterministic
    per-CPV-division quality signal (ingest volume vs. feedback outcomes) and
    persists it as a recommendation. It deliberately does NOT auto-mutate
    `allowed_cpv_codes` — silently changing what we ingest from a heuristic/LLM is
    a governance risk; an operator (or the agent) applies it.

Every cycle is persisted to the `reflections` table (`metrics` + `actions` +
`narrative`). A Claude narrative is produced when an API key is configured;
otherwise a deterministic summary is used, so the cycle (and the tests) run fully
offline. The scheduler's `job_reflect` (Job 4 / G13) drives this daily.
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa

from app.core.config import get_settings
from app.db.models import AgentRun, Feedback, Match, Reflection, Tender
from app.db.session import SessionLocal
from app.matching.features import _norm_cpv
from app.matching.lr_weights import FeedbackRetrainer

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

REFLECTION_PROMPT = """You are the GTM Agent Reflection mechanism.
You are given a JSON blob of recent operational metrics and the concrete actions
the system just took (e.g. whether it retrained the matching model from user
feedback, and per-CPV advisory recommendations). Write a brief operational
summary for an operator:
1. What was the recent activity and feedback quality?
2. Were there any anomalies?
3. Did the model retrain, and what does that imply?
4. Which CPV categories (if any) should the operator review?
Keep it to a few sentences. Do not invent numbers not present in the data.
"""

# Deterministic CPV-advisory thresholds.
_CPV_MIN_TENDERS = 3   # don't opine on a category with too few ingested tenders
_CPV_MIN_FEEDBACK = 3  # ...or too little feedback to be meaningful
_CPV_NEG_AVG = -0.34   # mean rating at/below this → flag "review" (mostly down-votes)
_RECENT_RUNS = 10


def _llm_available() -> bool:
    """True when an Anthropic key is configured. Patched to False in tests so the
    suite uses the deterministic narrative (mirrors the email-drafter gate)."""
    return bool(get_settings().anthropic_api_key)


class Reflector:
    """Computes operational metrics, actuates feedback-driven retraining, and
    persists a per-cycle reflection record."""

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        client: Any | None = None,
        min_samples: int = 10,
    ) -> None:
        settings = get_settings()
        self.model = model or settings.anthropic_model
        # `client` is injectable so tests can exercise the Claude path with a fake.
        self._client = client
        self.min_samples = min_samples

    # ── metrics ───────────────────────────────────────────────────────────────

    def compute_metrics(self, session: Session) -> dict[str, Any]:
        """Deterministic snapshot of recent runs + feedback + the CPV advisory."""
        n_runs = session.scalar(sa.select(sa.func.count()).select_from(AgentRun)) or 0
        recent_goals = list(
            session.scalars(
                sa.select(AgentRun.goal).order_by(AgentRun.created_at.desc()).limit(_RECENT_RUNS)
            ).all()
        )

        fb_rows = session.execute(sa.select(Feedback.rating, Feedback.features)).all()
        ratings = [int(r) for (r, _f) in fb_rows]
        n_feedback = len(ratings)
        n_pos = sum(1 for r in ratings if r > 0)
        n_neg = sum(1 for r in ratings if r < 0)
        n_trainable = sum(1 for (_r, f) in fb_rows if f)
        avg_rating = round(sum(ratings) / n_feedback, 3) if n_feedback else None

        return {
            "agent_runs_total": int(n_runs),
            "recent_run_goals": recent_goals,
            "feedback_total": n_feedback,
            "feedback_pos": n_pos,
            "feedback_neg": n_neg,
            "feedback_trainable": n_trainable,
            "avg_rating": avg_rating,
            "cpv_recommendations": self._cpv_recommendations(session),
        }

    @staticmethod
    def _cpv_recommendations(session: Session) -> list[dict[str, Any]]:
        """Per CPV-division (2-digit) advisory from ingest volume vs. feedback.

        Volume = how many tenders carry the division; feedback = ratings on
        matches for those tenders (via `feedback → match → tender`). Advisory
        only — nothing here mutates the ingest filter (decision B).
        """
        volume: dict[str, int] = defaultdict(int)
        for (cpvs,) in session.execute(sa.select(Tender.cpv_codes)).all():
            for div in {_norm_cpv(c)[:2] for c in (cpvs or []) if _norm_cpv(c)}:
                volume[div] += 1

        agg: dict[str, dict[str, int]] = defaultdict(lambda: {"n": 0, "sum": 0})
        fb_rows = session.execute(
            sa.select(Tender.cpv_codes, Feedback.rating)
            .select_from(Feedback)
            .join(Match, Match.id == Feedback.match_id)
            .join(Tender, Tender.id == Match.tender_id)
        ).all()
        for (cpvs, rating) in fb_rows:
            for div in {_norm_cpv(c)[:2] for c in (cpvs or []) if _norm_cpv(c)}:
                agg[div]["n"] += 1
                agg[div]["sum"] += int(rating)

        recs: list[dict[str, Any]] = []
        for div in sorted(set(volume) | set(agg)):
            if volume.get(div, 0) < _CPV_MIN_TENDERS:
                continue
            n = agg[div]["n"]
            avg = round(agg[div]["sum"] / n, 3) if n else None
            if n >= _CPV_MIN_FEEDBACK and avg is not None and avg <= _CPV_NEG_AVG:
                recommendation = "review"  # consider deprioritising in ingest
            elif n == 0:
                recommendation = "no_signal"  # ingesting but no feedback yet
            else:
                recommendation = "keep"
            recs.append(
                {
                    "cpv_division": div,
                    "tender_volume": volume.get(div, 0),
                    "feedback_count": n,
                    "avg_rating": avg,
                    "recommendation": recommendation,
                }
            )
        return recs

    # ── actions ───────────────────────────────────────────────────────────────

    def _maybe_retrain(self, session: Session) -> dict[str, Any]:
        """Run the feedback-driven LR retrain. The retrainer self-guards (returns
        `insufficient` below threshold / single-class) and only imports sklearn
        when it actually fits — so this stays cheap and CI-safe when there's not
        enough feedback. Any failure is contained so the cycle still persists."""
        try:
            return FeedbackRetrainer(min_samples=self.min_samples).retrain(session)
        except Exception as exc:  # e.g. sklearn missing once eligible, or a fit error
            logger.warning("reflect: retrain failed: %s", exc)
            return {"status": "error", "error": str(exc)}

    # ── narrative ─────────────────────────────────────────────────────────────

    def _get_client(self) -> Any | None:
        if self._client is not None:
            return self._client
        if not _llm_available():
            return None
        import anthropic

        self._client = anthropic.Anthropic(api_key=get_settings().anthropic_api_key)
        return self._client

    def _narrate(self, metrics: dict[str, Any], actions: dict[str, Any]) -> tuple[str, str]:
        """Return (narrative, source). Claude when available, else deterministic."""
        client = self._get_client()
        if client is not None:
            try:
                payload = json.dumps(
                    {"metrics": metrics, "actions": actions}, ensure_ascii=False, default=str
                )
                response = client.messages.create(
                    model=self.model,
                    max_tokens=1024,
                    system=REFLECTION_PROMPT,
                    messages=[{"role": "user", "content": "Recent activity (JSON):\n" + payload}],
                )
                return response.content[0].text, "claude"
            except Exception as exc:
                logger.warning("reflect: Claude narrative failed, using deterministic: %s", exc)
        return self._deterministic_narrative(metrics, actions), "deterministic"

    @staticmethod
    def _deterministic_narrative(metrics: dict[str, Any], actions: dict[str, Any]) -> str:
        lines = [
            "Reflection summary:",
            f"- Agent runs (total): {metrics['agent_runs_total']}",
            (
                f"- Feedback: {metrics['feedback_total']} "
                f"({metrics['feedback_pos']}+ / {metrics['feedback_neg']}-), "
                f"avg {metrics['avg_rating']}"
            ),
        ]
        retrain = (actions or {}).get("retrain") or {}
        status = retrain.get("status")
        if status == "retrained":
            lines.append(
                f"- Retrained the matching LR on {retrain['n_samples']} feedback samples "
                "— served model updated."
            )
        elif status == "insufficient":
            lines.append(
                f"- Retrain skipped: {retrain['n_samples']}/{retrain.get('min_required')} "
                "labelled samples (need both up- and down-votes)."
            )
        elif status == "error":
            lines.append(f"- Retrain errored: {retrain.get('error')}.")

        flagged = [
            r for r in metrics.get("cpv_recommendations", []) if r["recommendation"] == "review"
        ]
        if flagged:
            divs = ", ".join(f"{r['cpv_division']} (avg {r['avg_rating']})" for r in flagged)
            lines.append(f"- CPV categories to review (advisory): {divs}.")
        return "\n".join(lines)

    # ── orchestration ─────────────────────────────────────────────────────────

    def reflect(
        self,
        session: Session | None = None,
        act: bool = True,
        narrate: bool = True,
    ) -> dict[str, Any]:
        """Run one reflection cycle and persist a `reflections` row.

        `act=True` actuates the feedback-driven retrain (the weights lever). CPV
        recommendations are always advisory. Returns the persisted record's
        contents (`id`, `metrics`, `actions`, `narrative`).
        """
        own_session = session is None
        if own_session:
            session = SessionLocal()
        try:
            metrics = self.compute_metrics(session)
            actions: dict[str, Any] = {"cpv_applied": False}  # advisory only (decision B)
            if act:
                actions["retrain"] = self._maybe_retrain(session)

            narrative, source = self._narrate(metrics, actions) if narrate else ("", "skipped")
            actions["narrative_source"] = source

            record = Reflection(metrics=metrics, actions=actions, narrative=narrative)
            session.add(record)
            session.commit()
            return {
                "id": str(record.id),
                "metrics": metrics,
                "actions": actions,
                "narrative": narrative,
            }
        finally:
            if own_session:
                session.close()

    def run_daily_summary(self) -> str:
        """Back-compat entry point — runs a full cycle, returns the narrative."""
        return self.reflect()["narrative"]


if __name__ == "__main__":
    print("Running reflection cycle...")
    result = Reflector().reflect()
    print("=== Reflection ===")
    print(result["narrative"])
    print("actions:", result["actions"])
