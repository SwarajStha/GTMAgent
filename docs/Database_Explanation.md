# Database explanation

Reference for teammates. Snapshot of the GTMAgent Postgres schema as of **2026-07-01** (migrations `0001` → `0015` applied). The 2026-06-17 base content below (sample rows, per-table prose) is kept; the table inventory, migration history, and the agent-table sections are updated to the current head.

> Earlier snapshot (2026-05-17, migrations `0001`+`0002`) is preserved in the
> sample-row blocks below — those small 5-row samples predate the full awards
> back-fill and are kept as illustrative examples, not current counts.

## At a glance

- **Engine**: Postgres 16 with the `pgvector` extension (image `pgvector/pgvector:pg16`), running in Docker via `docker-compose.yml`.
- **Schema management**: Alembic migrations in [backend/app/db/migrations/versions/](../backend/app/db/migrations/versions/). **Fifteen** migrations applied (`0001` → `0015`) — see [§ Migration history](#migration-history).
- **ORM**: SQLAlchemy 2.x typed `Mapped[]` models in [backend/app/db/models.py](../backend/app/db/models.py).
- **Connection strings** (see [README](../README.md#connection-strings)):
  - `DATABASE_URL` — pooled, port `6543`, used by the FastAPI app at runtime.
  - `DATABASE_URL_DIRECT` — direct, port `5432`, used by Alembic only.
  - `DATABASE_URL_TEST` — direct, db `gtm_test`, used by the pytest fixtures.

### Table inventory (14 tables + `alembic_version`)

> Updated 2026-07-01: rows + columns below reflect migrations through `0015`. The
> three tables added since the original 2026-06-17 snapshot — `reflections` (`0011`),
> `agent_sessions` (`0014`), `tender_reports` (`0015`) — are listed at the end;
> `tenders` gained `description` (`0012`) + `tender_profile` (`0013`), `matches`
> gained 9 v5 feature columns (`0009`), and `feedback` gained `features` + a nullable
> `match_id` (`0010`).

| Table | Phase | Status | Purpose |
|---|---|---|---|
| `tenders` | 2 (Job 1) | **populated** (~3k rows) | Active EU procurement notices polled from TED |
| `awards` | 2 (Job 2) | **populated** (~21k rows after full back-fill) | Historic contract awards from TED — who won what |
| `companies` | 2 (Job 2) | **populated** (~15k rows) | Canonical legal entities resolved from award winners |
| `documents` | 2 (Job 3) | **populated** | PDF tender dossiers (downloaded from `tenders.document_url`) + extracted text |
| `company_profiles` | 3 | **populated** | Matchable supplier profiles (capability text + 384-d embedding), derived from award winners |
| `matches` | 3 | **populated** | Tender × company-profile scoring results (+ 9 v5 LR feature cols, `0009`) |
| `emails` | 4 | **populated** | Outreach drafts — supplier + buyer recipient types |
| `feedback` | 5 | live (endpoint) | Thumbs-up/down ratings + feature snapshot (drives LR retraining) |
| `embeddings` | future | empty | Generic vector store for cross-model embeddings |
| `agent_runs` | 6 | live (agent) | Records each completed Claude agent execution (goal, steps, output) |
| `reflections` | 6 (G9) | live | One row per reflection cycle (metrics / actions / narrative) — `0011` |
| `agent_sessions` | 6 (G22) | live | Resumable agent conversation (messages/steps/pending/run_state) — `0014` |
| `tender_reports` | 6 (G28) | live | Saved agent analyses (narrative + ranked-match snapshot, FK `tender_id`) — `0015` |
| `alembic_version` | meta | n/a | Tracks which migration is currently applied (head: `0015`) |

> Row counts above are the dev-DB state after the full awards back-fill (exported
> to [`exports/`](../exports/README.md)). `tenders` / `company_profiles` /
> `matches` / `emails` reflect the matching-pipeline smoke run (one tender ranked,
> top suppliers drafted) — see
> [matching_pipeline_smoke_record.md](matching_pipeline_smoke_record.md).

## Relationship map

The schema has **two disconnected sub-graphs** by design — there is no direct FK between them.

```
┌─ INGESTION (live) ─────────────────────────────────────────────────┐
│                                                                    │
│   tenders ──┐                          awards                      │
│   (int PK)  │                          (int PK)                    │
│             ├──> documents.tender_id   │                           │
│             │                          └──> companies.id           │
│             └──> matches.tender_id          (via winner_canonical_id)│
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
        │  Layer 1: companies + their awards ──build_company_profiles──┐
        ▼                                                              ▼
┌─ MATCHING / EMAILS (live) ─────────────────────────────────────────┐
│                                                                    │
│   company_profiles ──(source_company_id → companies.id, the bridge) │
│   (UUID PK)                                                         │
│                                                                    │
│   matches ──┬──> company_profiles.id   ┌── emails.match_id          │
│   (UUID PK) ├──> tenders.id            ├── emails.tender_id         │
│             └── (Layer 2 writes these) └── (supplier + buyer drafts)│
│                                                                    │
│   emails ───┬──> feedback.email_id                                 │
│   matches ──┴──> feedback.match_id                                 │
│                                                                    │
│   embeddings (no FKs, vectors keyed by source_type+source_id)       │
│   agent_runs (no FKs, one row per Claude agent execution)           │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

**The bridge between the two sub-graphs is `company_profiles.source_company_id`**
(a nullable FK to `companies.id`). Layer 1 of the matcher
(`build_company_profiles`) walks each award-winner `companies` row + its `awards`
history and derives a matchable `company_profiles` row from it. So the two halves
are no longer disconnected at runtime — they are joined by the profile-builder,
not by a row-level FK on `awards`.

### The roles of each table in matching

The mapping from "tenders + awards + scraping":

tenders — the demand side. Live procurement opportunities. Each row is "someone wants X built / X service supplied — bid by date Y". These are what we're matching for.
company_profiles (populated) — the supply side. The pool of suppliers we rank. Each row is a capability profile (capability text + 384-d embedding). In the MVP these are **derived from award winners** by the profile builder (`source_company_id → companies.id`); web scraping to enrich them is future work.

awards (populated, ~21k rows) — historical signal AND the seed for the supply side. Tells us who has actually won past contracts in each CPV category. Uses:
Build the pool: the profile builder turns each award-winner company + its award history into a `company_profiles` row.

Discover/validate candidates: companies that consistently win in our target CPV categories are strong matches.

So the matching pipeline is tenders × company_profiles → matches, and awards (via companies) is what currently populates company_profiles.

```

Two important design decisions explained below:

- **Awards are NOT children of tenders.** TED publishes Contract Notices (CN → `tenders`) and Contract Award Notices (CAN → `awards`) as separate publications, each with their own `publication-number`. They share a procedure-level relationship in TED metadata, but not at row-level for our purposes.
- **There are two company-like tables (`companies` and `company_profiles`) on purpose.** They serve different concerns — see the per-table sections below.

```

### Tenders table explained:

Job 1's smoke fetched notices with publication-date >= today - 7 days and scope=ACTIVE, so they were freshly published and still accepting bids. Checking the deadline column against today (2026-05-17):

ted_notice_id	buyer_country	deadline	status
326612-2026	DEU	2026-06-23	open (~5 weeks left)
326614-2026	CZE	2026-05-26	open (~9 days left)
326620-2026	CHE	2026-06-25	open (~5 weeks left)
326647-2026	FRA	2026-06-16	open (~4 weeks left)
326659-2026	LVA	2026-06-15	open (~4 weeks left)

All five are still open today. The Czech one (326614) is closest to expiring.

One small subtlety: TED's scope=ACTIVE means "currently published", not "currently open for bids". The deadline column is what tells us if a tender is still accepting submissions. Today they're the same thing (all 5 are both published and open), but a tender can be published-and-expired (deadline passed but TED still shows it). The matching pipeline in Phase 3 will need to filter out expired ones — easy with a WHERE deadline > now() clause.

---

## Populated tables

### `tenders` — ~10 rows, populated by Job 1

Source of all open EU procurement notices we want to match companies against. One row per TED Contract Notice (CN). Upserted by [poll_contract_notices()](../backend/app/ingestion/ted_client.py) keyed on `ted_notice_id`.

> The sample rows below are the original 5-row Job-1 smoke (2026-05-17), kept as
> an illustration of the column shapes. Run a fresh `--days N` poll to add more.

**Columns:**

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | autoincrement |
| `ted_notice_id` | varchar(64) | UNIQUE INDEX — upsert key (e.g. `326612-2026`) |
| `title` | text, nullable | English where available, otherwise first language TED returns |
| `buyer_name` | text, nullable | Multilingual unwrapped to a single string |
| `buyer_country` | varchar(8), nullable | ISO 3166-1 **alpha-3** (DEU, CZE, …) |
| `cpv_codes` | jsonb (list) | EU Common Procurement Vocabulary classifications, deduped |
| `deadline` | timestamptz, nullable | Earliest binding submission deadline across lots |
| `budget_eur` | float, nullable | TED reports values flat across lots — we take the first numeric |
| `currency` | varchar(8), nullable | Often EUR but not always (see Czech row below — CZK) |
| `status` | varchar(32) | Default `'active'` |
| `document_url` | text, nullable | Buyer portal URL, fed to Job 3 (dossier download) |
| `is_restricted` | bool | True for portal-locked PDFs (not parsed yet — always `false` today) |
| `raw_json` | jsonb | Full original TED notice envelope — kept verbatim for evidence/audit |
| `ingested_at` | timestamptz | When first inserted |
| `updated_at` | timestamptz | Bumped on every upsert (use to confirm freshness) |

**Sample rows** (3 of 5):

```
id              | 1
ted_notice_id   | 326612-2026
title           | Germany – Clinic construction work – Krankenhaus Wittmund gGmbH 2. BA...
buyer_name      | Krankenhaus Wittmund gGmbH
buyer_country   | DEU
cpv_codes       | ["45215130", "45432200", "44800000", "44812400"]
deadline        | 2026-06-23 04:00:00+02
budget_eur      | (null)
currency        | (null)
status          | active
document_url    | https://www.evergabe.de/unterlagen/019dfc77-.../zustellweg-auswaehlen
is_restricted   | false
raw_json        | { ... full TED v3 notice — see scripts/README.md to inspect }
ingested_at     | 2026-05-16 09:35:03
updated_at      | 2026-05-16 09:35:13
```

```
id              | 2
ted_notice_id   | 326614-2026
title           | Czechia – Carriageway resurfacing works – D11 Oprava AB...
buyer_name      | Ředitelství silnic a dálnic s. p.
buyer_country   | CZE
cpv_codes       | ["45233223"]
deadline        | 2026-05-26 04:00:00+02
budget_eur      | 1353000000
currency        | CZK
status          | active
document_url    | http://www.tenderarena.cz/profily/RSD
```

```
id              | 3
ted_notice_id   | 326620-2026
title           | Switzerland – IT services: consulting, software development, Internet...
buyer_name      | Spital Männedorf
buyer_country   | CHE
cpv_codes       | ["72000000", "48814400"]
deadline        | 2026-06-25 04:00:00+02
budget_eur      | (null)
```

### `awards` — ~21k rows after the full back-fill (populated by Job 2)

Historic contract awards. One row per TED Contract Award Notice (CAN) where a winner was selected. Notices that were cancelled-without-winner (`BT-142-LotResult = clos-nw`) are intentionally skipped at ingest time. Upserted by [backfill_awards()](../backend/app/ingestion/awards_client.py) keyed on `ted_notice_id`. The full 24-month back-fill produced **~21,015 awards / ~15,129 companies** (exported to [`exports/`](../exports/README.md) for the ML model).

**Columns** (the last block is the migration `0007` ML-enrichment set):

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | autoincrement |
| `ted_notice_id` | varchar(64) | UNIQUE INDEX — upsert key (e.g. `82677-2026`) |
| `cpv_code` | varchar(32), nullable | First CPV from the notice (awards have many; we keep the primary) |
| `buyer_name` | text, nullable | The org that issued the procurement |
| `buyer_country` | varchar(8), nullable | ISO alpha-3 |
| `winner_raw_name` | text, **NOT NULL** | Winner name as TED returned it, pre-canonicalisation |
| `winner_canonical_id` | int, FK → `companies.id`, nullable | Set by `resolve_or_create` during ingest |
| `contract_value_eur` | float, nullable | Awarded contract value. **Read with `contract_currency` — TED does NOT convert to EUR. `-1`/`0` are "not disclosed" sentinels.** |
| `award_date` | date, nullable | Contract conclusion / winner decision date |
| `n_offers_received` | int, nullable | How many tenders were submitted for the winning lot |
| `raw_json` | json | Full original TED notice — preserved for evidence |
| `ingested_at` | timestamptz | When first inserted |
| `notice_title` | text, nullable | Contract title — **original language** (multilingual) |
| `description` | text, nullable | Full scope text — **original language**; richest semantic signal for matching |
| `procedure_type` | varchar(32), nullable | eForms code: `open` / `restricted` / `neg-w-call` / … |
| `nuts_code` | varchar(16), nullable | NUTS-3 region of the work (buyer region fallback) |
| `winner_identifier` | varchar(64), nullable | Winner tax/registration id from TED (secondary dedup key) |
| `winner_country` | varchar(8), nullable | Winner country (alpha-3) |
| `contract_currency` | varchar(8), nullable | Currency of `contract_value_eur` (17 currencies seen — PLN, CHF, …) |

**Sample rows** (3 of 5):

```
id                   | 1
ted_notice_id        | 82677-2026
cpv_code             | 45262700
buyer_name           | НАЦИОНАЛЕН ПАРК - МУЗЕЙ "ШИПКА - БУЗЛУДЖА"
buyer_country        | BGR
winner_raw_name      | Билдинг Комфорт ООД
winner_canonical_id  | 1                         ← FK to companies.id=1
contract_value_eur   | 6902951.61
award_date           | 2026-01-15
n_offers_received    | 6
raw_json             | { ... full TED v3 notice }
ingested_at          | 2026-05-17 09:51:26
```

```
id                   | 2
ted_notice_id        | 82719-2026
cpv_code             | 45214200
buyer_name           | Landeshauptstadt München, Baureferat
buyer_country        | DEU
winner_raw_name      | Fischnaller Stahl & Glas GmbH
winner_canonical_id  | 2                         ← FK to companies.id=2
contract_value_eur   | 667964.00
award_date           | 2025-09-25
n_offers_received    | 13
```

```
id                   | 4
ted_notice_id        | 82749-2026
cpv_code             | 45000000
buyer_name           | Vollenweider Baurealisation GmbH      ← Swiss private buyer
buyer_country        | CHE
winner_raw_name      | DE_Scheco AG
winner_canonical_id  | 4                         ← FK to companies.id=4
contract_value_eur   | 251056.70
award_date           | 2026-02-04
n_offers_received    | 6
```

### `companies` — ~15k rows, populated by Job 2 via entity resolution

Canonical legal entities, one row per unique winning organisation across all awards. Variant spellings ("Hochtief AG" / "Hochtief Aktiengesellschaft") collapse to one row. Populated by [entity_resolution.resolve_or_create()](../backend/app/ingestion/entity_resolution.py), which since migration `0008` is **identifier-first**: it matches on `registration_id` (tax id) when present, else on the normalised `resolution_key`.

**Columns:**

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | autoincrement — the **only** hard-unique column now |
| `canonical_name` | text | INDEX (not unique since `0008`) — first raw name we saw |
| `resolution_key` | text | INDEX (not unique since `0008`) — normalised dedup key |
| `registration_id` | varchar(64), nullable, indexed | Tax/registration id from `winner-identifier`; stronger dedup key than name when present |
| `aliases` | json (list of str) | All raw names we've seen mapping to this entity |
| `country` | varchar(8), nullable | Inherited from the award's buyer (winner-country would be better — future improvement) |
| `created_at` | timestamptz | When this entity was first encountered |

> **Why the unique constraints were relaxed (`0008`)**: `registration_id` lets two
> distinct legal entities that happen to share a trading name occupy two rows
> (correctly), and merges variant spellings that share an id. So name/key can no
> longer be globally unique — dedup is enforced in `resolve_or_create`, not by a DB
> constraint. `clean_identifier()` rejects junk ids (all-zeros, textual placeholders
> like German `"keine Angabe"` = "no information") that would otherwise false-merge
> every firm reporting them onto one row.

**Normalisation logic** (in `normalise_name()`, the fallback when no `registration_id`):
1. Lowercase + strip whitespace
2. Delete punctuation `[,.&/\\-]` (so "A.B. Bau" → "ab bau", not "a b bau")
3. Collapse internal whitespace
4. Strip known legal suffixes (gmbh, ag, ltd, sa, srl, aktiengesellschaft, etc.) from the end, iteratively
5. Fall back to lowercased original if normalisation produces an empty string

**Sample rows** (all 5 — small enough to show in full):

```
id  | canonical_name                  | resolution_key            | aliases                              | country
----+---------------------------------+---------------------------+--------------------------------------+--------
 1  | Билдинг Комфорт ООД              | билдинг комфорт оод       | ["Билдинг Комфорт ООД"]              | BGR
 2  | Fischnaller Stahl & Glas GmbH   | fischnaller stahl glas    | ["Fischnaller Stahl & Glas GmbH"]   | DEU
 3  | EMF Fenstertechnik              | emf fenstertechnik        | ["EMF Fenstertechnik"]              | DEU
 4  | DE_Scheco AG                    | de_scheco                 | ["DE_Scheco AG"]                    | CHE
 5  | MSR Gerdes GmbH                 | msr gerdes                | ["MSR Gerdes GmbH"]                 | DEU
```

Worth noticing in this sample:

- **`Fischnaller Stahl & Glas GmbH` → `fischnaller stahl glas`** — both the `&` (punctuation) and the `gmbh` suffix were stripped. If we ingest "Fischnaller Stahl und Glas Aktiengesellschaft" later, the same `resolution_key` will match and the new spelling will be added to `aliases` without creating a duplicate row.
- **`DE_Scheco AG` → `de_scheco`** — the `_` underscore is currently NOT in our punctuation set, so it survives. **Improvement candidate**: add `_` to the punctuation regex.
- **`Билдинг Комфорт ООД` → `билдинг комфорт оод`** — the Bulgarian legal-form suffix `ООД` (≈ Ltd) is not in our `LEGAL_SUFFIXES` list, so it isn't stripped. **Improvement candidate**: extend the suffix list with non-Latin equivalents (Bulgarian `ООД`, Polish `Sp. z o.o.`, Romanian `S.R.L.`, etc.).

---

## Matching, emails & agent tables

These were scaffold-only in the 2026-05-17 snapshot; they are now populated by
the matching pipeline, the email backend, and the agent. Schemas reflect the
current models in [models.py](../backend/app/db/models.py).

### `documents` — Phase 2 (Job 3, populated)

One row per attempted-or-completed dossier download from `tenders.document_url`. `tender_id` is **UNIQUE** (at most one document per tender — the upsert keys on it). PyMuPDF extracts text into `extracted_text` (capped 100k chars).

Columns: `id INT PK`, `tender_id INT FK→tenders.id (UNIQUE)`, `source_url TEXT`, `storage_path TEXT (nullable)`, `extracted_text TEXT (nullable)`, `is_restricted BOOL`, `download_failed BOOL`, `file_hash VARCHAR(64) (sha256 dedup)`, `downloaded_at TIMESTAMP (nullable)`.

Two independent failure flags: `is_restricted = True` when the URL returned 401/403 (portal needs login); `download_failed = True` for non-auth failures (timeout, 5xx, non-PDF body). There is **no** `filename` or `text_content` column — the email backend derives a display label from `storage_path`/`source_url`, and the text column is `extracted_text`.

### `company_profiles` — Phase 3 (populated by the profile builder)

The matchable **supply side**. Distinct from `companies`: `company_profiles` holds capability text + an embedding for semantic matching. In the MVP, [profile_builder.build_company_profiles()](../backend/app/matching/profile_builder.py) derives one row per award-winner `companies` row (no web scraping yet — capability text = name + CPV codes + regions). UUID PK to match `matches`.

Columns: `id UUID PK`, `name TEXT`, `country VARCHAR(8)`, `website TEXT`, `capabilities JSONB` (`{text, cpv_codes, deal_size_eur, regions}`), `certifications JSONB`, **`embedding Vector(384)`** (MiniLM-L6 dimension), **`source_company_id INT FK→companies.id (UNIQUE, nullable)`** — the idempotent upsert key + bridge back to the legal entity, `created_at`, `updated_at`.

### `matches` — Phase 3 (populated)

Result rows from the matching pipeline. One row per (`tender`, `company_profile`) pair the pipeline scored. `MatchingPipeline.run` clears and rewrites a tender's matches on each run (idempotent recompute).

Columns: `id UUID PK`, `tender_id INT FK→tenders.id`, `company_id UUID FK→company_profiles.id`, four sub-scores (`semantic_score`, `budget_score`, `location_score`, `qualification_score`), `final_score FLOAT (idx)`, `weights JSONB` (the combiner weights used — default `0.40/0.20/0.20/0.20`, will become LR-learned), `explanation TEXT`, `is_disqualified BOOL`.

`final_score` is the sort key for ranked output.

### `emails` — Phase 4 (populated)

Outreach drafts. Two recipient types share the table via `recipient_type`:
- **`supplier`** — per-match outreach to the matched company (`POST /api/v1/emails/{match_id}/generate`).
- **`buyer`** — per-tender digest recommending the top suppliers, anchored to the tender's top match (`POST /api/v1/emails/buyer/{tender_id}/generate`).

Drafts are **Claude-written and evidence-grounded** (G10), with a deterministic template fallback. Listable via `GET /api/v1/emails/` (added 2026-07-01).

Columns: `id UUID PK`, `match_id UUID FK→matches.id`, **`recipient_type VARCHAR(16)`** (`'supplier'`/`'buyer'`), **`tender_id INT FK→tenders.id (nullable)`**, `subject TEXT`, `body TEXT`, `evidence JSONB` (the tender/company/score context that grounded the draft), `status VARCHAR(32)` (default `'draft'`), `sent_at TIMESTAMPTZ`.

### `feedback` — Phase 5 (endpoint live)

Thumbs-up/thumbs-down ratings on matches (+ optional email). `POST /api/v1/feedback` writes these; `FeedbackRetrainer` + `POST /api/v1/feedback/retrain` consume them to retrain the LR weights (G8).

Columns: `id UUID PK`, **`match_id UUID FK (nullable, ON DELETE SET NULL)`**, `email_id UUID FK (nullable)`, `rating SMALLINT` (+1 or −1), `comment TEXT`, **`features JSONB`** (10-feature snapshot taken at submit time, `0010`, so a row stays usable for retraining after its match is re-computed).

### `agent_runs` — Phase 6 (written by the agent)

One row per completed agent run (including truncated ones). Powers the reflection loop, which reads recent runs + feedback.

Columns: `id UUID PK`, `goal TEXT`, `steps JSONB` (the tool calls + args the agent made), `output TEXT`, `created_at`, `updated_at`.

### `reflections` — Phase 6 / G9 (migration `0011`)

One row per `Reflector.reflect()` cycle — the "wired-to-behaviour" record of a reflection.

Columns: `id UUID PK`, `metrics JSONB` (run/feedback stats + per-CPV advisory), `actions JSONB` (e.g. the feedback→LR retrain outcome; CPV advice is advisory-only), `narrative TEXT` (Claude when a key is set, else deterministic), `created_at`, `updated_at`.

### `agent_sessions` — Phase 6 / G22 (migration `0014`)

A **resumable** agent conversation. When the agent calls `ask_user` (tender disambiguation) the loop pauses (`status='awaiting_input'`) and persists here; `POST /api/v1/agent/run/{id}/continue` resumes it.

Columns: `id UUID PK`, `goal TEXT`, `dry_run BOOL`, `status VARCHAR(16)` (`running`/`awaiting_input`/`done`/`error`), `messages JSONB` (the Anthropic conversation array as plain dicts), `steps JSONB`, `pending JSONB` (the open `ask_user` question + `tool_use_id` + options), `run_state JSONB` (per-run guard counters: caged-ingest counts, zero-match flag), `created_at`, `updated_at`.

### `tender_reports` — Phase 6 / G28 (migration `0015`)

A **saved agent analysis** for a tender — the narrative + a self-contained snapshot of the ranked matches (survives a later re-match). History kept (many per tender). Read by the Tender-detail "Saved analyses" panel via `GET /api/v1/tenders/{id}/reports`.

Columns: `id UUID PK`, **`tender_id INT FK→tenders.id (idx)`**, `session_id UUID FK→agent_sessions.id (nullable, SET NULL)`, `goal TEXT`, `narrative TEXT`, `suppliers JSONB` (top-N `{match_id, company_name, final_score, sub-scores}`), `created_at`, `updated_at`.

### `embeddings` — future

Generic cross-model vector store, intentionally separate from `company_profiles.embedding` so we can store mpnet (768-dim) or multilingual-e5 (1024-dim) vectors alongside the 384-dim MiniLM ones without changing column types.

Columns: `id UUID PK`, `source_type VARCHAR(32) (idx)` (e.g. `'tender'`, `'company'`, `'document'`), `source_id UUID (idx)`, `model_name VARCHAR(64)`, **`vector Vector(768)`**.

### `alembic_version` — meta

Single-row table that records the migration head Alembic believes is applied. Today it should contain `0015_tender_reports`.

```sql
SELECT version_num FROM alembic_version;
-- 0008_company_registration_id
```

If `alembic upgrade head` ever fails mid-migration, this row is what you check to see what state the DB thinks it's in.

---

## Migration history

| Revision | File | What it did |
|---|---|---|
| `0001_initial_schema` | [0001](../backend/app/db/migrations/versions/0001_initial_schema.py) | Created all scaffold tables in one shot, plus `CREATE EXTENSION vector`. **Was edited in place during Job 1** to give `tenders` its final Job-1 shape (int PK, JSONB cpv_codes, etc.) before any production data existed — see [docs/architecture.md](architecture.md) for the rationale. |
| `0002_awards_companies` | [0002](../backend/app/db/migrations/versions/0002_awards_companies.py) | **Additive** — dropped the scaffold `awards` (UUID PK) and recreated it with the Job 2 shape (int PK, `winner_canonical_id` FK to new `companies` table). Created `companies`. Preserves Job 1 tender rows. |
| `0003_add_documents` | [0003](../backend/app/db/migrations/versions/0003_add_documents.py) | **Additive** — dropped the scaffold `documents` and recreated it with the Job 3 shape (int PK, UNIQUE FK to tenders, `source_url`/`storage_path`/`extracted_text`/`file_hash`/`is_restricted`/`download_failed`/`downloaded_at`). |
| `0004_agent_runs` | [0004](../backend/app/db/migrations/versions/0004_agent_runs.py) | Created `agent_runs` (Phase 6 — records Claude agent executions). |
| `0005_company_profile_source` | [0005](../backend/app/db/migrations/versions/0005_company_profile_source.py) | Added `company_profiles.source_company_id` (UNIQUE FK to `companies.id`) — the profile-builder's idempotent upsert key + bridge between the two sub-graphs. |
| `0006_buyer_emails` | [0006](../backend/app/db/migrations/versions/0006_buyer_emails.py) | Added `emails.recipient_type` (`supplier`/`buyer`) + `emails.tender_id` to support the buyer-facing digest. |
| `0007_award_enrichment` | [0007](../backend/app/db/migrations/versions/0007_award_enrichment.py) | Added 7 ML-enrichment columns to `awards` (`notice_title`, `description`, `procedure_type`, `nuts_code`, `winner_identifier`, `winner_country`, `contract_currency`). |
| `0008_company_registration_id` | [0008](../backend/app/db/migrations/versions/0008_company_registration_id.py) | Added `companies.registration_id` (tax id); **relaxed** `canonical_name`/`resolution_key` from UNIQUE to plain indexes so identifier-first resolution can split/merge entities. |
| `0009_match_v5_features` | [0009](../backend/app/db/migrations/versions/0009_match_v5_features.py) | Added 9 v5 LR feature columns to `matches` (cpv-4/2-digit, nuts-exact/country, value, value-in-range, country-match, company-size, competition). Legacy 4 sub-scores kept as rollups. |
| `0010_feedback_features` | [0010](../backend/app/db/migrations/versions/0010_feedback_features.py) | Added `feedback.features` (10-feature snapshot at submit time) + made `feedback.match_id` nullable / `ON DELETE SET NULL` so re-matching preserves training data (G8). |
| `0011_reflections` | [0011](../backend/app/db/migrations/versions/0011_reflections.py) | Created `reflections` (one row per reflection cycle — `metrics`/`actions`/`narrative`, G9). |
| `0012_tender_description` | [0012](../backend/app/db/migrations/versions/0012_tender_description.py) | Added `tenders.description` (TED BT-24) — feeds the matcher's tender embedding text. |
| `0013_tender_profile` | [0013](../backend/app/db/migrations/versions/0013_tender_profile.py) | Added `tenders.tender_profile` JSONB — the Understanding layer's structured output (G11), source of `required_certifications` for the cert gate (G12). |
| `0014_agent_sessions` | [0014](../backend/app/db/migrations/versions/0014_agent_sessions.py) | Created `agent_sessions` — resumable agent conversation (messages/steps/pending/run_state), backs the `ask_user` pause/resume (G22). |
| `0015_tender_reports` | [0015](../backend/app/db/migrations/versions/0015_tender_reports.py) | Created `tender_reports` — saved agent analyses (narrative + ranked-match snapshot, FK `tender_id`, nullable FK `session_id`, G28). Current **head**. |

**Forward pattern (Job 3+)**: new migration files only. Do NOT edit committed migrations in place. The Job 1 in-place edit was a one-time exception while the DB had no production data.

To apply migrations on a fresh DB:

```powershell
cd backend
.\.venv\Scripts\alembic.exe upgrade head
```

To inspect the current head:

```powershell
docker exec -it gtmagent-db-1 psql -U gtm -d gtm -c "SELECT version_num FROM alembic_version;"
```

---

## Roadmap status

Done:

1. ✅ **Job 3 — dossier downloader** populates `documents`. PDFs fetched from `tenders.document_url`, PyMuPDF extracts text into `documents.extracted_text`.
2. ✅ **Phase 3 — matching engine** populates `company_profiles` (derived from award winners by the profile builder — not yet a curated/scraped pool), then runs the `MatchingPipeline` to compute sub-scores and write `matches`. Weights snapshot to `matches.weights`.
3. ✅ **Phase 4 — generation** drafts supplier + buyer emails from match evidence, writes to `emails` (deterministic for now; Claude-written is the planned upgrade).
4. ✅ **Phase 6 — agent** records executions to `agent_runs`; the reflection loop reads them + `feedback`.

Still pending:

5. **Job 4 — APScheduler loop** — run Jobs 1–3 on a schedule (daily tender poll, weekly awards back-fill). CLI exists; the loop is a stub.
6. **Understanding layer** — Claude `FieldExtractor` to turn raw notices + dossier text into a structured `TenderProfile`.
7. **Phase 5 — feedback → retraining** — `feedback` is captured; the LR weight learner that retrains from it (and refreshes embeddings) is not yet wired. Also where multi-tenant auth lands.
8. **Richer `company_profiles`** — enrich capability text from dossier text / web scraping so semantic scores stop being thin (see [matching_pipeline_smoke_record.md](matching_pipeline_smoke_record.md)).

---

## How to inspect the live DB

The fastest path is the psql one-liners documented in [backend/scripts/README.md](../backend/scripts/README.md). Highlights:

```powershell
# Row counts across all tables
docker exec -it gtmagent-db-1 psql -U gtm -d gtm -c "
  SELECT 'tenders' AS t, count(*) FROM tenders
  UNION ALL SELECT 'awards', count(*) FROM awards
  UNION ALL SELECT 'companies', count(*) FROM companies
  UNION ALL SELECT 'documents', count(*) FROM documents
  UNION ALL SELECT 'matches', count(*) FROM matches
  ORDER BY 1;"

# Joined view: each award → its canonical winner
docker exec -it gtmagent-db-1 psql -U gtm -d gtm -c "
  SELECT a.ted_notice_id, c.canonical_name, a.buyer_country,
         a.contract_value_eur, a.award_date
  FROM awards a
  LEFT JOIN companies c ON c.id = a.winner_canonical_id
  ORDER BY a.award_date DESC;"

# Schema of a single table (column list + indexes + FKs)
docker exec -it gtmagent-db-1 psql -U gtm -d gtm -c "\d awards"
```

For GUI inspection, [DBeaver](https://dbeaver.io/) connected to `localhost:5432`, db `gtm`, user `gtm`, password `gtm` works well — JSONB columns expand inline.

---

## Pointers

- **Model definitions**: [backend/app/db/models.py](../backend/app/db/models.py)
- **Migrations**: [backend/app/db/migrations/versions/](../backend/app/db/migrations/versions/)
- **Decision log (why each table is shaped the way it is)**: [docs/architecture.md](architecture.md)
- **Inspection cheatsheet + smoke harnesses**: [backend/scripts/README.md](../backend/scripts/README.md)
- **Quickstart / how to run the stack**: [../README.md](../README.md)
