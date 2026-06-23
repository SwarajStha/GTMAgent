"""LLM-driven field extraction (Claude) with a deterministic fallback.

`FieldExtractor.extract_tender(raw_text, base=...)` turns a tender's free text
into a structured `TenderProfile`. The LLM is asked ONLY to *enrich* — to read
the procurement text and surface the fields the raw TED columns cannot give us:
a short summary, the **required certifications**, the required capabilities, and
keywords. The deterministic, already-trustworthy columns (CPV, title, budget,
country, deadline) are passed in as `base` and used as the ground truth: they are
never overwritten by the model, and they are the whole profile when no LLM is
available.

This mirrors the email drafter (`app/generation/drafter.py`): a lazy, injectable
Anthropic client, the stable `client.messages.create(...)` surface (pinned
`anthropic` 0.39.0), JSON-only output, and a graceful fallback on a missing key /
SDK error / malformed output so callers always get a valid profile. Tests force
the offline path via the `_offline_extractor` conftest fixture; the Claude path
is exercised with an injected fake client.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any

from app.core.config import get_settings
from app.understanding.schemas import CompanyProfile, TenderProfile

# The model may enrich only these list/text fields; the structured `base` fields
# (cpv_code/title/budget/country/deadline) are authoritative and never replaced.
_TENDER_SYSTEM = (
    "You are a procurement analyst extracting structured data from an EU public "
    "tender notice. Read the provided tender text and return ONLY a JSON object "
    "with these keys: "
    '"summary" (1-2 sentence plain-English summary), '
    '"required_certifications" (list of standards/certifications the tender '
    "explicitly requires, e.g. \"ISO 9001\", \"ISO 14001\", \"EMAS\"; [] if none "
    "are stated), "
    '"required_capabilities" (list of concrete capabilities/works the supplier '
    "must be able to deliver), "
    '"keywords" (list of salient domain terms), '
    '"language" (ISO-639-1 code of the tender text, e.g. "de", "cs"). '
    "Extract only what is present in the text — never invent a certification or "
    "requirement that is not stated. Respond with ONLY the JSON object."
)
_COMPANY_SYSTEM = (
    "You are an analyst extracting a structured supplier profile from company "
    "text. Return ONLY a JSON object with these keys: "
    '"description" (1-2 sentence summary), '
    '"capabilities" (list of what the company can deliver), '
    '"certifications" (list of standards/certifications the company holds; [] if '
    "none are stated), "
    '"languages" (list of ISO-639-1 codes). '
    "Extract only what is present — never invent a certification. Respond with "
    "ONLY the JSON object."
)

_MAX_TEXT_CHARS = 12000


def _llm_available() -> bool:
    """Whether a live Claude call should be attempted. Patched to False in tests
    (see the `_offline_extractor` conftest fixture) so the suite stays offline
    regardless of a populated `.env`."""
    return bool(get_settings().anthropic_api_key)


def _as_str_list(value: Any) -> list[str]:
    """Coerce model output to a clean, deduped list of non-empty strings."""
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item).strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            out.append(text)
    return out


class FieldExtractor:
    """Wraps the Claude client and the extraction prompts (LLM enrich + fallback)."""

    def __init__(
        self, client: Any = None, model: str | None = None, max_tokens: int = 1024
    ) -> None:
        self._client = client
        self.model = model or get_settings().anthropic_model
        self.max_tokens = max_tokens

    # ── tender ───────────────────────────────────────────────────────────────

    def extract_tender(self, raw_text: str, base: dict[str, Any] | None = None) -> TenderProfile:
        """Return a `TenderProfile`. `base` carries the trustworthy structured
        columns (cpv_code/title/budget_eur/buyer_country/buyer_name/deadline);
        the LLM only adds summary/certifications/capabilities/keywords/language."""
        base = base or {}
        profile = self._tender_fallback(base, raw_text)
        if self._client is None and not _llm_available():
            return profile
        try:
            enriched = self._enrich_tender(raw_text)
        except Exception:
            # Missing SDK, transport/auth error, malformed output — keep the
            # deterministic base profile.
            return profile
        # Merge: LLM enriches the soft fields; base columns stay authoritative.
        return profile.model_copy(
            update={
                "summary": enriched.get("summary", profile.summary) or profile.summary,
                "required_certifications": _as_str_list(enriched.get("required_certifications")),
                "required_capabilities": _as_str_list(enriched.get("required_capabilities")),
                "keywords": _as_str_list(enriched.get("keywords")),
                "language": (enriched.get("language") or profile.language) or None,
            }
        )

    @staticmethod
    def _tender_fallback(base: dict[str, Any], raw_text: str) -> TenderProfile:
        cpvs = base.get("cpv_codes") or []
        cpv_code = str(base.get("cpv_code") or (cpvs[0] if cpvs else "")).strip()
        title = str(base.get("title") or "").strip()
        deadline = base.get("deadline")
        if not isinstance(deadline, date):
            deadline = None
        return TenderProfile(
            cpv_code=cpv_code,
            title=title or (raw_text[:120].strip() if raw_text else "(untitled tender)"),
            summary=(base.get("summary") or "").strip(),
            buyer_country=base.get("buyer_country"),
            buyer_name=base.get("buyer_name"),
            budget_eur=base.get("budget_eur"),
            deadline=deadline,
        )

    def _enrich_tender(self, raw_text: str) -> dict[str, Any]:
        return self._call(_TENDER_SYSTEM, raw_text)

    # ── company ──────────────────────────────────────────────────────────────

    def extract_company(self, raw_text: str, base: dict[str, Any] | None = None) -> CompanyProfile:
        """Return a `CompanyProfile`. `base` carries name/country/website; the LLM
        adds description/capabilities/certifications/languages."""
        base = base or {}
        profile = CompanyProfile(
            name=str(base.get("name") or "").strip() or "(unknown company)",
            country=base.get("country"),
            website=base.get("website"),
        )
        if self._client is None and not _llm_available():
            return profile
        try:
            enriched = self._call(_COMPANY_SYSTEM, raw_text)
        except Exception:
            return profile
        return profile.model_copy(
            update={
                "description": str(enriched.get("description") or "").strip(),
                "capabilities": _as_str_list(enriched.get("capabilities")),
                "certifications": _as_str_list(enriched.get("certifications")),
                "languages": _as_str_list(enriched.get("languages")),
            }
        )

    # ── Claude plumbing ──────────────────────────────────────────────────────

    def _get_client(self) -> Any:
        if self._client is None:
            from anthropic import Anthropic  # lazy: keep import off the hot path

            self._client = Anthropic(api_key=get_settings().anthropic_api_key)
        return self._client

    def _call(self, system: str, raw_text: str) -> dict[str, Any]:
        payload = (raw_text or "").strip()[:_MAX_TEXT_CHARS]
        response = self._get_client().messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": f"Tender/company text:\n{payload}"}],
        )
        text = "".join(
            getattr(block, "text", "")
            for block in response.content
            if getattr(block, "type", None) == "text"
        )
        return self._parse_json(text)

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("no JSON object in model output")
        obj = json.loads(text[start : end + 1])
        if not isinstance(obj, dict):
            raise ValueError("model output was not a JSON object")
        return obj
