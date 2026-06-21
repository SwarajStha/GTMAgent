"""LLM email drafter (Claude, evidence-constrained) with a deterministic fallback.

`EmailDrafter.draft(evidence, recipient_type)` returns
``{"subject", "body", "generator"}``. It calls Claude (model from settings) when
an API key is configured, constraining the model to facts present in `evidence`;
on a missing key, an SDK/transport error, or a draft that fails
`EmailValidator`, it falls back to a deterministic template so callers always get
a usable draft. This is the single drafting path shared by the `/emails`
endpoints and the agent's `draft_email` tool (G10).

Uses the stable `client.messages.create(...)` surface (compatible with the
pinned `anthropic` 0.39.0). The Anthropic client is created lazily only when a
draft is actually requested with a key present, and is injectable for tests.
"""
from __future__ import annotations

import json
from typing import Any

from app.core.config import get_settings
from app.generation.validator import EmailValidator

_SUPPLIER_SYSTEM = (
    "You are a B2B business-development assistant writing a short, professional "
    "outreach email to a supplier company about an EU public-sector tender that may "
    "fit them. Use ONLY facts present in the provided evidence JSON — never invent "
    "company details, contract values, deadlines, certifications, or capabilities. "
    "Be concrete and not salesy; keep the body under ~180 words. "
    'Respond with ONLY a JSON object of the form {"subject": "...", "body": "..."} '
    "and nothing else."
)
_BUYER_SYSTEM = (
    "You are a B2B procurement assistant writing a short, professional digest to a "
    "public buyer, recommending the suppliers that best match their tender. Use ONLY "
    "facts present in the provided evidence JSON — never invent suppliers, fit scores, "
    "or details. Keep the body under ~200 words. "
    'Respond with ONLY a JSON object of the form {"subject": "...", "body": "..."} '
    "and nothing else."
)


def _llm_available() -> bool:
    """Whether a live Claude call should be attempted. Patched to False in tests
    so the suite stays offline regardless of a populated `.env`."""
    return bool(get_settings().anthropic_api_key)


class EmailDrafter:
    """Drafts outreach emails via Claude, with a deterministic template fallback."""

    def __init__(
        self,
        client: Any = None,
        model: str | None = None,
        max_tokens: int = 1024,
    ) -> None:
        self._client = client
        self.model = model or get_settings().anthropic_model
        self.max_tokens = max_tokens
        self._validator = EmailValidator()

    def draft(self, evidence: dict[str, Any], recipient_type: str = "supplier") -> dict[str, str]:
        """Return ``{"subject", "body", "generator"}`` for the given evidence.

        `generator` is ``"claude"`` when the LLM produced a valid draft, else
        ``"template"`` (deterministic fallback).
        """
        if self._client is None and not _llm_available():
            return self._fallback(evidence, recipient_type)
        try:
            draft = self._draft_with_claude(evidence, recipient_type)
            ok, _reasons = self._validator.validate(draft, evidence)
            if not ok:
                return self._fallback(evidence, recipient_type)
            return {**draft, "generator": "claude"}
        except Exception:
            # Missing SDK, transport/auth error, malformed output — degrade safely.
            return self._fallback(evidence, recipient_type)

    # ── Claude path ─────────────────────────────────────────────────────────

    def _get_client(self) -> Any:
        if self._client is None:
            from anthropic import Anthropic  # lazy: keep import off the hot path

            self._client = Anthropic(api_key=get_settings().anthropic_api_key)
        return self._client

    def _draft_with_claude(self, evidence: dict[str, Any], recipient_type: str) -> dict[str, str]:
        system = _BUYER_SYSTEM if recipient_type == "buyer" else _SUPPLIER_SYSTEM
        payload = json.dumps(evidence, ensure_ascii=False, default=str)[:12000]
        user = (
            "Write the email from this evidence. Respond with ONLY the JSON object.\n\n"
            f"Evidence:\n{payload}"
        )
        response = self._get_client().messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(
            getattr(block, "text", "")
            for block in response.content
            if getattr(block, "type", None) == "text"
        )
        return self._parse_json(text)

    @staticmethod
    def _parse_json(text: str) -> dict[str, str]:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("no JSON object in model output")
        obj = json.loads(text[start : end + 1])
        return {"subject": str(obj["subject"]).strip(), "body": str(obj["body"]).strip()}

    # ── deterministic fallback ──────────────────────────────────────────────

    def _fallback(self, evidence: dict[str, Any], recipient_type: str) -> dict[str, str]:
        if recipient_type == "buyer":
            draft = _buyer_template(evidence)
        else:
            draft = _supplier_template(evidence)
        return {**draft, "generator": "template"}


def _supplier_template(evidence: dict[str, Any]) -> dict[str, str]:
    """Deterministic supplier-outreach draft from the evidence dict."""
    tender = evidence.get("tender") or {}
    company = evidence.get("company") or {}
    score = (evidence.get("score_breakdown") or {}).get("final_score") or 0.0
    title = tender.get("title") or f"TED notice {tender.get('ted_notice_id')}"
    company_name = company.get("name") or "there"
    buyer = tender.get("buyer_name") or "the public buyer"
    deadline = tender.get("deadline") or "the published deadline"
    explanation = evidence.get("match_explanation") or "The match score indicates a relevant fit."

    subject = f"{title} - opportunity for {company_name}"
    body = (
        f"Hi {company_name} team,\n\n"
        f"We found a public tender from {buyer}: {title}. "
        f"The current match score is {score:.0%}, based on the tender context and your company "
        "profile.\n\n"
        f"Why this looks relevant: {explanation}\n\n"
        f"The listed deadline is {deadline}. I can share the parsed tender profile and evidence "
        "table if this opportunity is relevant for your pipeline.\n\n"
        "Best,\nGTM Agent"
    )
    return {"subject": subject, "body": body}


def _buyer_template(evidence: dict[str, Any]) -> dict[str, str]:
    """Deterministic buyer-digest draft from the evidence dict."""
    tender = evidence.get("tender") or {}
    suppliers = evidence.get("recommended_suppliers") or []
    title = tender.get("title") or f"TED notice {tender.get('ted_notice_id')}"
    buyer = tender.get("buyer_name") or "team"
    lines = [
        f"{i}. {s.get('name')}"
        + (f" ({s.get('country')})" if s.get("country") else "")
        + f" — fit {(s.get('final_score') or 0.0):.0%}"
        + (f"\n   {s.get('explanation')}" if s.get("explanation") else "")
        for i, s in enumerate(suppliers, start=1)
    ]
    subject = f"Recommended suppliers for {title} ({tender.get('ted_notice_id')})"
    body = (
        f"Hi {buyer},\n\n"
        f"We analysed the market for your tender '{title}' and identified "
        f"{len(suppliers)} supplier(s) that strongly match its requirements:\n\n"
        + "\n".join(lines)
        + "\n\nThese rankings combine semantic fit, budget alignment, location, and "
        "qualifications. I'm happy to share the full evidence table for any of them.\n\n"
        "Best,\nGTM Agent"
    )
    return {"subject": subject, "body": body}
