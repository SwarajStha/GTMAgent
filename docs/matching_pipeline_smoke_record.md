# Matching pipeline — live smoke record

- **Date:** 2026-06-16
- **Branch:** `feat/pipeline-integration-ML-backend-frontend`
- **Environment:** dev DB (Docker `gtmagent-db-1`, `gtm` database), real MiniLM
  (`all-MiniLM-L6-v2`, cached locally), `truststore` SSL injection.
- **Nature:** one-off inline run (no output file is produced by the pipeline —
  it prints to stdout and writes rows to the DB). This document is the record.

> The pipeline does **not** emit a results file. Ranked results are persisted to
> the `matches` table; the buyer digest to the `emails` table. For a file-based
> artifact, query the DB (see "Reproduce") or formalize `scripts/matching_smoke.py`.

---

## What was done, step by step

1. **DB up + schema current.** Started the `db` compose service and ran
   `alembic upgrade head` (applies `0005_company_profile_source` +
   `0006_buyer_emails`). Dev DB held **10 tenders, 10 companies, 10 awards**.
2. **Layer 1 — build supplier pool.** `build_company_profiles(session)` derived
   a `company_profiles` row from each award-winner `company` (capability text =
   name + CPV codes + regions; deal size from past contract values; MiniLM
   embedding). Result: `{processed: 10, created: 10, updated: 0}` on first run,
   `{created: 0, updated: 10}` on re-run (**idempotent ✓**).
3. **Layer 2 — match a tender.** `MatchingPipeline().run(tender_id=1, top_n=5)`
   embedded the tender, scored all 10 profiles, persisted `matches`.
4. **Layer 3 — buyer email.** `generate_buyer_email(tender_id=1, top_n=3)`
   produced a buyer-facing digest of the top-3 suppliers.

---

## Output (captured 2026-06-16)

```
[Layer 1] {'processed': 10, 'created': 0, 'updated': 10}     # re-run = idempotent
[Layer 2] tender id=1: "Germany – Clinic construction work – Krankenhaus Wittmund" | country=DEU
[matches] 5 ranked:
  0.423  Fischnaller Stahl & Glas GmbH      sem=0.31 bud=0.50 loc=1.00 qual=0.00
  0.408  MSR Gerdes GmbH                    sem=0.27 bud=0.50 loc=1.00 qual=0.00
  0.396  EMF Fenstertechnik                 sem=0.24 bud=0.50 loc=1.00 qual=0.00
  0.257  Билдинг Комфорт ООД                sem=0.29 bud=0.50 loc=0.20 qual=0.00
  0.255  VESIBA, s.r.o.                     sem=0.29 bud=0.50 loc=0.20 qual=0.00

[Layer 3] buyer email:
  subject: Recommended suppliers for Germany – Clinic construction work –
           Krankenhaus Wittmund gGmbH ... Malerarbeiten (326612-2026)
    - Fischnaller Stahl & Glas GmbH    fit=42%
    - MSR Gerdes GmbH                  fit=41%
    - EMF Fenstertechnik              fit=40%
```

**Interpretation:** the full two-sided flow works on real data
(profiles → ranked matches → buyer email), and the **location signal is
correct** — German suppliers top a German tender (loc=1.00) while the
Bulgarian/Czech winners drop to 0.20. Ranking is currently location-dominated
because the other signals are weak on this data (see below).

**DB side effects (dev only, rebuildable):** 10 `company_profiles`, 5 `matches`
for tender 1, and 1 buyer `email` row were written.

---

## Needs patching / follow-ups

| # | Severity | Finding | Fix |
|---|---|---|---|
| 1 | 🟡 script-only | First run **crashed on Windows console encoding** (`cp1252`) while *printing* a Cyrillic company name. The pipeline + DB writes were unaffected; re-run with `PYTHONIOENCODING=utf-8` was clean. | A future `scripts/matching_smoke.py` must force UTF-8 stdout (`sys.stdout.reconfigure(encoding="utf-8")`). Not a pipeline bug. |
| 2 | 🟠 scoring (actionable) | **`qualification = 0.00` for every match.** Tender CPVs (`45215130`, `45432200`, …) never exactly overlap the companies' award CPVs, but CPV codes are hierarchical — these are all construction (division `45`). Exact/token matching misses related categories. | Make `score_qualification` (or the terms passed in `pipeline._tender_terms`) match on **CPV prefixes** (e.g. shared 4–5 digit group / `45` division), not exact codes. Highest-leverage scoring fix. |
| 3 | 🟠 data quality | **`semantic ≈ 0.24–0.31` (thin).** `company_profiles` capability text is only name + CPV + region. | Enrich `capabilities.text` from `documents.extracted_text` (dossiers) and/or web scraping, so semantic similarity becomes meaningful. (Known limitation from the branch review.) |
| 4 | 🟢 data | **`budget = 0.50` (MISSING_FILL) everywhere** — tender 1 has no `budget_eur` (TED contract notices often omit it). | Derive budget from TED estimated-value fields / dossier where available; otherwise accept as no-signal. |
| 5 | 🟢 note | Country matching is alpha-3 exact/substring (`DEU`). Worked here. | No change needed for now. |

**Net:** no code defects in the pipeline itself — items #2–#4 are accuracy
improvements (CPV-prefix qualification is the one worth doing soon), #1 is a
smoke-script ergonomics fix.

---

## Reproduce

```bash
cd backend && PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe - <<'PY'
import truststore; truststore.inject_into_ssl()
import sqlalchemy as sa
from app.db.session import SessionLocal
from app.db.models import Tender
from app.matching.profile_builder import build_company_profiles
from app.matching.pipeline import MatchingPipeline
from app.api.v1.emails import generate_buyer_email
with SessionLocal() as s:
    print(build_company_profiles(s))
    tid = s.scalar(sa.select(Tender.id).order_by(Tender.id).limit(1))
    for r in MatchingPipeline().run(tid, session=s, top_n=5):
        print(r["final_score"], r["company_name"])
    print(generate_buyer_email(tid, db=s, top_n=3).subject)
PY
```

Or via the API once the server is running:
`POST /api/v1/matches/run/{tender_id}` then `POST /api/v1/emails/buyer/{tender_id}/generate`.
