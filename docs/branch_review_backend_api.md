# Branch review — `codex/backend-api-implementation-plan` (MVP backend APIs + frontend)

Merged to `main` via **PR #7** (`1874c2b`, 2026-06-15; feature work
`ad47068`, 2026-06-14). This is the first **read/serve layer** of the
product: it turns the data the ingestion jobs already write (`tenders`,
`awards`, `companies`) into HTTP endpoints, and wires a Vue 3 dashboard on
top of them with a graceful sample-data fallback. It is the third teammate
branch reviewed here — see also
[branch_review_easy_demo.md](branch_review_easy_demo.md) (Phase 3 matching
spike) and [branch_review_agent_controller.md](branch_review_agent_controller.md)
(Phase 6 agent layer).

> **TL;DR.** The **tenders / awards / companies** read paths are real and
> work against live DB rows. The **matches → emails → feedback** path is
> wired front-to-back but has **no data producer** behind it (the matching
> pipeline is still a Phase-3 stub and `company_profiles` is empty), so the
> frontend silently runs on sample data there. ~~And the **email-generation
> endpoint is currently broken**~~ **[Fixed 2026-06-15 on
> `fix/integration-fix-for-merged-PRs` — see Gap #1.]** It referenced three
> `Document` columns that don't exist and failed against a real database
> (2 failing tests). It was a small, contained bug.

---

## Files added / touched

**Backend (API layer):**
- `backend/app/api/v1/tenders.py` — `GET /` (paged+filtered list), `GET /{id}`
  (numeric id *or* TED notice id). Real, working.
- `backend/app/api/v1/awards.py` — `GET /` (paged+filtered), `GET /{id}`,
  with an outer-join to `companies` for the resolved winner name. Real,
  working.
- `backend/app/api/v1/companies.py` — `GET /` (with award-count / total-value
  / latest-date rollups), `GET /{id}` (+ recent awards). Real, working.
- `backend/app/api/v1/matches.py` — `GET /` (ranked, filtered), `GET /{id}`
  (+ email summaries). Correct, but reads `matches`/`company_profiles` which
  have no producer yet (see Gaps).
- `backend/app/api/v1/emails.py` — `POST /{match_id}/generate` (deterministic
  template draft), `GET /{email_id}`. **Broken — see Gap #1.**
- `backend/app/api/v1/feedback.py` — `POST /` (thumbs up/down, validates the
  match/email relationship). Real, working; nothing consumes it yet.
- `backend/app/main.py` — registers the awards/companies routers (the agent
  router was added separately by PR #5).

**Backend (tests):** `test_tenders_api.py`, `test_matches_api.py`,
`test_emails_api.py`, `test_feedback_api.py`, `test_awards_companies_api.py`,
plus 2 lines in `test_stubs.py`. All mock the DB with `MagicMock` /
`SimpleNamespace` (see Gap #7).

**Frontend:**
- `src/stores/{tenders,matches,emails}.ts` — Pinia stores that call the API
  and fall back to `sampleData.ts` on any error.
- `src/stores/sampleData.ts` — hardcoded demo fixtures (321 lines).
- `src/views/{HomeView,TendersView,MatchesView,EmailsView}.vue` — the four
  dashboard screens.
- `src/components/AppShell.vue`, `src/style.css` — nav shell + Tailwind
  component classes.

---

## How it works

- **Pagination/filtering convention is consistent across all list
  endpoints**: `limit` (1–200, default 50) + `offset`, a `{items, total,
  limit, offset}` envelope, and an `_apply_filters()` helper per router. This
  is a clean, repeatable shape — good baseline for any future list endpoint.
- **Tenders**: `GET /{tender_id}` cleverly accepts both the integer PK and
  the `ted_notice_id` string (`tender_id.isdigit()` branch). List is ordered
  by deadline-ascending then ingest-recency. The detail response adds
  `raw_json`.
- **Awards / companies**: awards outer-join `companies` to surface
  `winner_canonical_name`; companies aggregate award history
  (`count`/`sum`/`max`) via a grouped select. `companies.py` reuses
  `awards.py`'s `_award_out` / `AwardOut` directly — nice de-duplication.
- **Matches**: three-way join `Match → Tender → CompanyProfile`, ordered by
  `final_score` desc. Filters: `tender_id`, `company_id`, `min_score`,
  `include_disqualified`. Detail adds linked `emails` summaries.
- **Emails**: `generate_email` collects an *evidence dict* (tender + company
  + score breakdown + document snippets), renders a **deterministic template**
  (`_draft_from_evidence`, no LLM call), and persists an `Email` row with
  `evidence` JSONB. This is a sensible "always works, no API key needed"
  baseline distinct from the Phase-4 Claude drafter.
- **Frontend stores** follow one pattern: `fetchAll()` calls the API, maps
  the response into the view model, sets `source = 'api'`; on **any** failure
  it swallows the error, loads `sampleData`, and sets `source = 'sample'`.
  This is why the dashboard looks fully populated even with an empty DB or a
  broken endpoint — convenient for demos, but it also **hides real failures**
  (see Gap #2).

---

## What works (and is genuinely reusable)

- **One fully-working end-to-end vertical slice exists**: TED ingestion →
  `tenders` table → `GET /api/v1/tenders/` → `TendersView`. With the 5 live
  tender rows already in the dev DB, this path serves real data today. Same
  for awards and companies (5 rows each) at the API level.
- **The list/detail/envelope/filter conventions** are solid and worth
  standardising on for every future endpoint.
- **`feedback.py` is correct and complete** for what it does: validates the
  match exists, validates the email (if given) belongs to that match, rejects
  `rating == 0`. It just has no downstream consumer yet (Phase 5).
- **The frontend information architecture** (Command dashboard, tender
  workbench with extracted-section panels, match ranking with score
  breakdown + client-side weight sliders, email draft/evidence/approve flow)
  matches the product vision in the project plan well — it's a good UI
  skeleton to grow into.
- **Sample-data fallback** makes the UI demoable on a fresh checkout with no
  backend — useful, as long as everyone understands `source: 'sample'` means
  "the API call failed."

---

## Gaps — what needs to change / be added

### 1. ✅ `POST /emails/{match_id}/generate` is broken (verified) — FIXED 2026-06-15

> **Resolved** on `fix/integration-fix-for-merged-PRs`: `generate_email` now
> orders by `Document.downloaded_at.desc().nulls_last()`, `_document_snippets`
> reads `document.extracted_text`, and a new `_document_label()` helper derives
> the snippet's display name from `storage_path`/`source_url` (no `filename`
> column exists). The mock test's `_document()` fake was corrected to mirror
> the real columns, and a new real-DB regression test
> (`test_generate_email_writes_real_draft`) exercises the actual schema so this
> can't silently regress. Full suite: **92 passed**. Original diagnosis kept
> below.



`emails.py` reads three `Document` attributes that **do not exist** on the
ORM model (`app/db/models.py` `Document` has `extracted_text` and
`downloaded_at`, no `created_at` / `text_content` / `filename`):

- `emails.py:202` — `.order_by(Document.created_at.desc())` → `Document` has
  no `created_at` (it doesn't use `TimestampMixin`; its timestamp is
  `downloaded_at`).
- `emails.py:114` — `document.text_content` → should be
  `document.extracted_text`.
- `emails.py:115,120` — `document.filename` → no such column. The closest
  identifier is the tender's `ted_notice_id` or `Document.source_url`.

The unit tests pass **only because they fake the DB** — `_document()` in
`test_emails_api.py` is a `SimpleNamespace(filename=..., text_content=...)`
and `db.scalars(...)` is a `MagicMock`, so the bogus query is never executed
against a real schema. Run against anything real and it raises:

```
$ pytest tests/test_emails_api.py -q
E   AttributeError: type object 'Document' has no attribute 'created_at'
...
2 failed, 3 passed
```

(Full-suite snapshot at review time: **2 failed, 82 passed, 7 errors** — the
7 errors are `test_dossier_downloader.py` needing the `gtm_test` Postgres DB,
i.e. environmental, not this branch's fault.)

**Fix** (small, contained): in `generate_email` order documents by
`Document.downloaded_at` (and tolerate NULLs), and in `_document_snippets`
read `document.extracted_text` and use `tender.ted_notice_id` /
`document.source_url` instead of `document.filename`. Then add a *real-DB*
test so this can't silently regress (see Gap #7).

### 2. 🟠 The `matches → emails → feedback` path has no data producer

The matches API joins `Match → Tender → CompanyProfile`, but:
- **`MatchingPipeline.run()` is a Phase-3 stub** (`app/matching/pipeline.py`
  ends in `...`). Nothing writes rows to `matches`.
- **`company_profiles` is empty** (Phase 5 — scraped capability profiles
  don't exist yet). `Match.company_id` FKs to `company_profiles.id`, *not* to
  the `companies` table the awards job populates.

So `GET /matches/` returns `[]` on real data, `generate_email` has no match
to generate from, and the dashboard quietly shows **sample data** instead.
Closing this is the central integration task: implement the matching pipeline
(port from the `easy_demo` spike) **and** decide how `company_profiles` gets
populated. The natural bridge: award-winner `companies` (Job 2) → build
`company_profiles` capability profiles (the `easy_demo` company JSON is
literally built from an award winner, *Bembé Parkett*) → match new tenders
against them. This conceptual link should be made explicit in the plan.

### 3. 🟠 Three divergent email-drafting code paths

There are now **three** ways an email gets written, and they don't agree:
- `emails.py:_draft_from_evidence` — deterministic template, no LLM (this
  branch). Works once Gap #1 is fixed.
- `generation/drafter.py:EmailDrafter.draft()` — Phase-4 Claude drafter,
  still a stub (`...`).
- The agent's `draft_email` tool (PR #5) calls the *stub* `EmailDrafter`, so
  it always errors — see agent review Remaining Gap #1.

Decide the contract: most likely `EmailDrafter` becomes the real Phase-4
implementation, the `/generate` endpoint calls it (with the deterministic
template as the no-API-key fallback), and the agent tool calls the same code
path. Right now they're three half-wired alternatives.

### 4. 🟡 Frontend doesn't surface awards, companies, or the agent

The backend ships `/awards`, `/companies`, and (via PR #5) `/agent/run`
endpoints, but the frontend has **no stores or views** for any of them — nav
is only Command / Tenders / Matches / Emails. The awards/companies data
(which actually works end-to-end) is invisible in the UI, and there's no way
to drive the agent from the dashboard. These are net-new screens to build if
they're in scope for the demo.

### 5. 🟡 Weight sliders are cosmetic (client-side only)

`MatchesView.vue`'s weight sliders recompute `adjustedScore()` purely in the
browser; nothing is POSTed back. The project plan wants manual weight
overrides to feed the LR retraining loop (Phase 5). As built, adjusting
weights changes the on-screen ranking but is forgotten on reload and never
reaches the backend. Needs a persistence endpoint (e.g.
`PATCH /matches/{id}/weights` or a per-tender weights store) once Phase 5
lands.

### 6. 🟡 Feedback is captured but unused

`POST /feedback/` correctly stores `{match_id, email_id?, rating, comment}`,
and the frontend submits from both the match and email views. But
`lr_weights.py` (the consumer) is still a stub, so feedback accumulates
without retraining anything yet. Expected — flagging it so the loop is
remembered when Phase 5 starts.

### 7. ✅ Tests are mock-based, which is exactly how Gap #1 shipped green — ADDRESSED 2026-06-15

Every API test uses `MagicMock` + `SimpleNamespace` stand-ins, so they
validate handler control-flow and response shaping but **never touch a real
schema** — a column that doesn't exist still "passes." The dossier tests
already proved out a real-Postgres `gtm_test` fixture in
`tests/conftest.py`; the new API tests (especially `emails`) should reuse it
for at least one happy-path-against-real-DB case each.

> **Resolved** on `fix/integration-fix-for-merged-PRs`: added
> `tests/test_api_real_db.py` — 10 real-Postgres tests covering tenders
> (list/get-by-id/get-by-notice + country/cpv/search filters), matches
> (list/detail + min_score/disqualified filters + linked email + email
> detail), awards (list/get + winner join + unresolved-winner NULL outer
> join), companies (rollups + recent awards + zero-award NULL aggregation),
> and feedback (match-only + with-email). **Finding: the email endpoint was
> the only router with schema drift** — all five other routers run correctly
> against the real schema, including the NULL-aggregation and outer-join edge
> cases. Full suite now **102 passed**. The per-router mock tests are kept
> (they're fast and exercise response shaping); the new file is the
> schema-drift guard.

### 8. 🟢 Minor

- ~~CORS is hardcoded to `http://localhost:5173`~~ **Fixed 2026-06-15** —
  now driven by the `CORS_ORIGINS` setting (comma-separated, default
  `http://localhost:5173`), parsed via `Settings.cors_origins_list` mirroring
  the `allowed_cpv_codes`/`cpv_code_list` pattern. `main.py` reads it instead
  of a literal list. Covered by `tests/test_config.py`.
- `recipientFor()` in `emails.ts` fabricates `sales@<website-domain>` as the
  recipient — clearly a placeholder; real outreach needs a real contact
  source.
- The matches store maps `final_score >= 0.8` → "ready" and uses
  `match.explanation` as evidence; once real matches exist, confirm these
  thresholds/fields line up with what the pipeline actually writes.

---

## End-to-end flow status (after this merge)

| Stage | Path | Status |
|---|---|---|
| Ingest tenders | TED → `tenders` | ✅ works (5 live rows) |
| Serve tenders | `GET /tenders` → `TendersView` | ✅ works on real data |
| Ingest awards/companies | TED → `awards` / `companies` | ✅ works (5+5 rows) |
| Serve awards/companies | `GET /awards`, `/companies` | ✅ API works; ❌ no UI |
| Understanding (extract) | `FieldExtractor` | ❌ stub (Phase 2) |
| Matching | `MatchingPipeline.run()` → `matches` | ❌ stub (Phase 3) — **blocks matches API** |
| Company profiles | populate `company_profiles` | ❌ empty (Phase 5) — **blocks matches API** |
| Serve matches | `GET /matches` → `MatchesView` | ⚠️ wired, but no data → sample fallback |
| Generate email | `POST /emails/{id}/generate` | ✅ fixed (Gap #1); needs a real `match` row to run on |
| Serve/edit email | `GET /emails`, `EmailsView` | ⚠️ wired, depends on generate |
| Feedback | `POST /feedback` | ✅ stores; ❌ nothing consumes it (Phase 5) |
| Agent | `POST /agent/run` | ⚠️ loop works; matching/draft tools dead (PR #5) |

---

## Suggested next steps (in order)

1. ~~**Fix Gap #1** (the `Document` field bug)~~ **Done 2026-06-15** —
   handler fixed + real-DB regression test added; suite is green (92 passed).
2. **Implement `MatchingPipeline.run()`** by porting the `easy_demo` spike
   (see [branch_review_easy_demo.md](branch_review_easy_demo.md)), writing
   real `matches` rows. Decide the `company_profiles` population strategy at
   the same time (Gap #2) — this is the keystone that lights up matches →
   emails → feedback and the agent's `find_matches` tool simultaneously.
3. **Reconcile the email-drafting paths** (Gap #3): make `EmailDrafter` real,
   route the endpoint and the agent tool through it.
4. **Build the missing UI** (awards/companies/agent) and **persist weight
   overrides + wire feedback into LR** (Gaps #4–#6) as Phase 5 work.
5. ~~**Backfill real-DB tests** for the API layer (Gap #7)~~ **Done
   2026-06-15** — `tests/test_api_real_db.py` (10 tests) guards all six
   routers against schema drift; confirmed the other five were already sound.
