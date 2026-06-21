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

---

## 2026-06-21 re-run — after Steps 2 & 3 (CPV-prefix qual + multilingual embedder)

- **What changed since the run above:** `score_qualification` now does CPV-prefix
  partial credit (G4); the embedder default is now
  `paraphrase-multilingual-MiniLM-L12-v2` (G5); `build_company_profiles` was
  re-run, populating the **full pool of 15,129** `company_profiles` (was 10).
- **Environment:** dev DB (Docker), real multilingual MiniLM, `truststore`,
  UTF-8 stdout. Pool: `tenders=10`, `company_profiles(embedded)=15129`.
- **Tender matched:** id=2 — *Czechia – Carriageway resurfacing works – D11*
  (CPV `45233223`, country CZE). (Tender 1 from the run above now has a buyer
  email referencing its matches, so re-matching it hits the FK bug logged as
  **G26**; an email-free construction tender was used instead.)

### Output (captured 2026-06-21)

```
[matches] top 8 of 15129 scored:
   final    sem   bud   loc  qual  company
   0.693   0.33  0.91  1.00  0.90  M – SILNICE a.s.            (Czech road builder)
   0.637   0.39  1.00  1.00  0.40  EUROVIA CZ a.s.
   0.622   0.41  1.00  1.00  0.30  FIRESTA-Fišer, rekonstrukce, stavby a.s.
   0.612   0.43  1.00  1.00  0.20  DIRS Brno s.r.o.
   0.604   0.31  1.00  1.00  0.40  STRABAG SIS a.s.
   0.602   0.36  1.00  1.00  0.30  DW STAVBY BRNO s.r.o.
   0.602   0.35  0.91  1.00  0.40  SWIETELSKY stavební s.r.o.
   0.594   0.28  1.00  1.00  0.40  PORR a.s.

[qual] 89/100 of top-100 have qualification > 0   (was 0/N on 2026-06-16)
[sem]  top-100 semantic range 0.17–0.44
[buyer email] subject: Recommended suppliers for Czechia – Carriageway resurfacing works – D11 ...
```

**Interpretation:** clear improvement. The top 8 are all genuine Czech
civil-engineering / road contractors (EUROVIA, STRABAG, SWIETELSKY, PORR are
real major EU infra firms) led by a literal road company on a road tender.
- **G4 confirmed fixed:** `qualification` now spans 0.20–0.90 and 89/100 of the
  top-100 are > 0 — the 2026-06-16 finding (`qualification=0.00` everywhere) is
  resolved.
- **G5 working:** the Czech-language tender title now relates to Czech profiles;
  semantic contributes to the ordering. Range is still modest (0.17–0.44) —
  that's the thin-profile-text limitation (**G6**, still open), not the embedder.
- **Location** stays correct (all CZ → 1.00 for a CZ tender).

### New findings logged to the gap tracker

- **G26 (🟠):** re-matching a tender that already has an email crashes on
  `emails_match_id_fkey` (the idempotent `DELETE FROM matches` is blocked by the
  referencing email). Fix in the Step 4 pipeline rework.
- **G7 (🟡, sharpened):** tender 2's `budget_eur` came through as **€1.353 B** —
  almost certainly an un-converted/sentinel value (the known *"contract_value_eur
  is not EUR-converted"* data caveat), which pushed `budget_score` to ~1.0. The
  budget signal needs FX normalisation + sentinel handling, not just
  missing-value handling.

---

## 2026-06-21 (later) — Step 4: v5 LR mode live

- **What changed:** the v5 model is now ported into `app/matching`. The pipeline
  runs in **LR mode** — v5-style hard filter → 10 features → trained Logistic
  Regression win-probability (`exports/model_params.json`, regenerated with
  intercept + scaler). Migration `0009` added the 9 feature columns; profiles
  refreshed with nuts/median/award_count (`{updated: 15129, embedded: 0}` — no
  re-embed). Activation: `run_pipeline.py` → `alembic upgrade head` →
  `build_company_profiles`.
- **Tender matched:** id=1 — *Germany – Clinic construction work – Krankenhaus
  Wittmund* (CPV `45215130, 45432200, 44800000, 44812400`, DEU, **budget None**).
  This is the tender that hit the G26 FK bug before; re-matching it now is also
  the **live G26 regression check**.

### Output (captured 2026-06-21)

```
[mode] LR scorer loaded: True  (features=10, intercept=-2.220)
[hard filter] 200 candidates scored (of 15129 in pool)

[matches] top 8 by LR win-probability:
   P(win)   sem cpv4 cpv2 nutsC ctry  val size  company
    0.266  0.43  1.0  1.0   0.5  1.0  0.5 0.15  Jaeger Ausbau GmbH + CO KG Leipzig
    0.265  0.43  1.0  1.0   0.5  1.0  0.5 0.15  Projekt- und Baumanagement Heinrich Schmid
    0.249  0.42  1.0  1.0   0.5  1.0  0.5 0.15  Bodentechnik Kretzschmar GmbH & Co. KG
    0.239  0.41  1.0  1.0   0.5  1.0  0.5 0.15  Guido Kleinemeyer Fliesenlegermeister
    0.227  0.40  1.0  1.0   0.5  1.0  0.5 0.15  Ernst & Herwig Hoch-und Tiefbau GmbH & Co.
    0.226  0.40 ...                            Wagner Schweißtechnik
    ...
[explain #1] Jaeger Ausbau: cpv_4digit=+1.56, nuts_country=+0.56, company_size=+0.23, nuts_exact=+0.22
[G26] re-match + buyer email OK
```

**Interpretation:**
- **LR mode is live**, hard filter narrowed 15,129 → 200 (**G3 working**), all 10
  feature columns persist, and `final_score` is now an LR win-probability with
  per-feature contributions for the explanation (**G1/G2 done**).
- **Rankings are sensible**: all top candidates are German construction / interior
  fit-out firms; flooring specialists (Bodentechnik Kretzschmar, a
  Fliesenlegermeister/tiler) surface for a tender carrying flooring CPV
  `45432200`. CPV-4 is the dominant driver in the #1 explanation, matching the
  trained coefficient (+1.26).
- **G26 fixed (live):** re-matching tender 1 — which carried a stale buyer email
  from the 2026-06-16 run — no longer raises `emails_match_id_fkey`; the email is
  recomputed cleanly.
- **Expected residuals:** P(win) sits at 0.22–0.27 and the top band is thin
  because this tender has **no budget and no NUTS** (value/nuts features flat at
  0.5) and all hard-filtered candidates are German construction (cpv/country
  saturated), so semantic (0.40–0.43) is the only discriminator — and semantic
  spread is still narrow (**G6** thin-profile-text, still open). These are data
  limitations, not pipeline defects. Absolute probabilities are lower than the
  Step 2/3 weighted scores by design (calibrated LR vs. a 0–1 blend).
