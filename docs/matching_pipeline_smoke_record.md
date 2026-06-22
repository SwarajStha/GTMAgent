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

---

## 2026-06-21 (later) — G6 (richer semantic text) + G7 (EUR budgets)

- **What changed:** `build_capability_text` now uses each company's award
  `notice_title` + `description` (v5-aligned, 4000-char cap); `money.to_eur`
  EUR-normalises award values + tender budgets and drops `-1/0` sentinels. Full
  profile re-embed run (`{updated: 15129, embedded: 15129}`). No migration, no v5
  re-run (both changes align the app to the existing v5 model).

### Output (captured 2026-06-21)

```
tender 1 | DEU | Germany – Clinic construction work – Krankenhaus Wittmund
  budget raw=None currency=None -> EUR None
  semantic across top-100: min=0.67 max=0.82 spread=0.15
    P=0.789  sem=0.79 bud=0.50 val_rng=0.5  MK Nordbau GmbH
    P=0.788  sem=0.78 bud=0.50 val_rng=0.5  Estrich - Stoll GmbH      (screed/flooring)
    P=0.782  sem=0.78 bud=0.50 val_rng=0.5  BTS Müller & Olschok GmbH
    P=0.777  sem=0.77 bud=0.50 val_rng=0.5  Herrndobler GmbH
    P=0.775  sem=0.77 bud=0.50 val_rng=0.5  C.A.H. GmbH

tender 2 | CZE | Czechia – Carriageway resurfacing works – D11
  budget raw=1353000000.0 currency=CZK -> EUR 54120000.0
  semantic across top-100: min=0.00 max=0.78 spread=0.78
    P=0.549  sem=0.78 bud=0.58 val_rng=1.0  SWIETELSKY stavební s.r.o.
    P=0.537  sem=0.67 bud=0.79 val_rng=1.0  SaM silnice a mosty a.s.   (roads & bridges)
    P=0.526  sem=0.66 bud=0.85 val_rng=1.0  TSS GRADE, a.s.
    P=0.479  sem=0.68 bud=0.75 val_rng=1.0  TOMI - REMONT a.s.
    P=0.478  sem=0.66 bud=0.74 val_rng=1.0  SWIETELSKY Rail CZ s.r.o.
```

**Interpretation — both wins confirmed:**
- **G6:** semantic cosines for relevant matches jumped from ~0.24–0.43 (Step 4) to
  **0.67–0.82** (clinic) and now span **0.00–0.78** (road) — the embeddings carry
  real procurement-description signal. Relevant specialists surface (Estrich/screed
  for a clinic; "silnice a mosty" = roads & bridges for a road tender). P(win) for
  relevant matches rose from ~0.27 to **~0.79** — the LR's strong semantic
  coefficient now acts on meaningful inputs (and the app's semantic distribution
  matches v5's training, reducing skew).
- **G7:** tender 2's `1.353 B CZK` now reads **€54.12 M** (a sane resurfacing
  value); budget / value_in_range features discriminate (0.58–0.85 / 1.0) instead
  of saturating at ~1.0. Tender 1 genuinely has no budget → 0.5 fill (correct).
- **Marked resolved:** G6, G7 (tracker R21/R22).

---

## 2026-06-22 — G13 (scheduler) + G9 (reflection wired to behaviour)

- **What changed:** real `IngestionScheduler` (APScheduler `BackgroundScheduler`,
  UTC) with 4 cron jobs — contracts (daily) / dossiers (daily) / awards (weekly) /
  reflect (daily) — opt-in via `scheduler_enabled` (default off), wired into the
  FastAPI `lifespan`. `Reflector.reflect()` rewritten to compute deterministic
  metrics, auto-run the feedback→LR retrain (weights lever), compute an advisory
  per-CPV recommendation (decision B — not auto-applied), and persist each cycle
  to the new `reflections` table (migration `0011`). Claude narrative when a key
  is present, deterministic fallback otherwise. `POST /agent/reflect` added.
- **Environment:** dev DB (Docker `gtmagent-db-1`, `gtm`), `0011` applied,
  `truststore` SSL, UTF-8 stdout. 244/244 backend tests; ruff-clean new code.

### Smoke A — scheduler wiring (no network, no DB)

```
start() -> True
  ingest_contracts   next_run=2026-06-23 03:00:00+00:00  cron hour=3  min=0
  download_dossiers  next_run=2026-06-23 03:30:00+00:00  cron hour=3  min=30
  ingest_awards      next_run=2026-06-23 04:00:00+00:00  cron dow=1 hour=4
  reflect            next_run=2026-06-23 05:00:00+00:00  cron hour=5  min=0
running after shutdown -> False
disabled start() -> False | jobs: []
```

All 4 jobs register with the configured, correctly-staggered next-runs; clean
shutdown; and disabled mode (the default) registers nothing and doesn't start.

### Smoke B — reflection cycle (dev DB; `Reflector().reflect()` == scheduled `job_reflect`)

```
feedback model file exists BEFORE: False
DB state: feedback=0 (pos=0 neg=0 trainable=0) tenders=10 reflections_before=0

[actions] {'cpv_applied': False,
           'retrain': {'status': 'insufficient', 'n_samples': 0, 'n_pos': 0,
                       'n_neg': 0, 'min_required': 10},
           'narrative_source': 'claude'}
[metrics] agent_runs_total=0  feedback_total=0  avg_rating=None
          cpv_recommendations=[{'cpv_division': '45', 'tender_volume': 9,
                                'feedback_count': 0, 'avg_rating': None,
                                'recommendation': 'no_signal'}]
[narrative] (Claude) grounded summary — cites 0 runs, the min-10 retrain
            threshold, and CPV-45 = 9 tenders / no_signal; no invented numbers.

feedback model file exists AFTER: False
reflections_after: 1 | narrative_source: claude
```

**Interpretation — wiring confirmed:**
- **G13:** the scheduled `reflect` callable runs the same code path the cron job
  would; jobs register and tear down cleanly.
- **G9 weights lever:** `retrain` correctly reported `insufficient` (0 feedback <
  10) and **wrote no model file** (before/after both False) — the lever is wired
  and safely inert without data. The actual-fit path is covered by the unit tests
  (`test_reflect_records_retrain_outcome` mocked; `test_retrain_writes_params_and_learns`
  real-sklearn, local).
- **G9 persistence:** exactly one `reflections` row written per cycle.
- **G9 CPV advisory:** deterministic — 9 of 10 tenders carry a CPV-45 code →
  `{division 45, volume 9, no_signal}`, `cpv_applied=False` (advisory only).
- **Claude path live-verified:** `narrative_source=claude`, narrative grounded in
  the real metrics (parallels the G10 live email verification).
- **Data-limited (not a defect):** an actual retrain firing needs ≥10 labelled
  feedback with both classes, which the dev DB doesn't have yet.

---

## 2026-06-22 — tender descriptions (BT-24) added + matching A/B

- **What changed:** the contract-notice poller now requests `description-proc`
  (+ `BT-24-Lot` fallback); new `tenders.description` column (migration `0012`);
  the matcher folds `tender.description` into `_tender_text`. This gives the
  demand side the same descriptive text the supply side already has (awards
  `description`, G6) and aligns serve-time tender text with v5's training
  (`notice_title + description`).
- **Backfill:** re-polled the 7-day window — `{fetched: 2986, new: 0, updated:
  2986, errors: 0}` (idempotent on `ted_notice_id`). **100% description coverage**
  on re-polled rows (2986/2996; the 10 pre-existing rows predate the field).
  Avg description ~669 chars, max ~6000.

### A/B smoke (read-only): tender 917 — Czechia hospital construction

Real multilingual MiniLM; same hard-filtered candidate set (101 of 15,129);
tender embedding text WITHOUT vs WITH the description.

```
old_text (title+cpv)   135 chars   ->   new_text (title+desc+cpv)  4034 chars
semantic cosine — OLD:  min 0.42  mean 0.59  max 0.74
semantic cosine — NEW:  min 0.44  mean 0.61  max 0.74
TOP-5 reshuffled: 3 of 5 retained; 2 new Czech builders surfaced
  (Podzimek a synove, PS-STAV Nachod)
```

**Interpretation (honest):** a modest aggregate lift (mean +0.02, min +0.02) plus
a real re-ranking — this tender's hard-filtered set is homogeneous (all Czech
construction firms, already title-similar), so the description mainly
**discriminates within** the set rather than shifting the whole distribution. The
larger structural wins: (a) **train/serve skew removed** (tender side now matches
v5's `notice_title+description` training and the company side's G6 text), and (b)
on tenders with generic titles the description carries most of the signal, so the
lift there is bigger. No retrain / re-embed needed — tenders embed on-the-fly per
match run.
