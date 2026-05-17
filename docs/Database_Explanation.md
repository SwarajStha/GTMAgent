# Database explanation

Reference for teammates. Snapshot of the GTMAgent Postgres schema as of **2026-05-17** (branch `feat/awards-back-fill`, migrations `0001` + `0002` applied).

## At a glance

- **Engine**: Postgres 16 with the `pgvector` extension (image `pgvector/pgvector:pg16`), running in Docker via `docker-compose.yml`.
- **Schema management**: Alembic migrations in [backend/app/db/migrations/versions/](../backend/app/db/migrations/versions/). Two migrations applied so far — see [§ Migration history](#migration-history).
- **ORM**: SQLAlchemy 2.x typed `Mapped[]` models in [backend/app/db/models.py](../backend/app/db/models.py).
- **Connection strings** (see [README](../README.md#environment)):
  - `DATABASE_URL` — pooled, port `6543`, used by the FastAPI app at runtime.
  - `DATABASE_URL_DIRECT` — direct, port `5432`, used by Alembic only.

### Table inventory (10 tables)

--- see docs/Table Sample/17-05-2026

| Table | Phase | Status | Purpose |
|---|---|---|---|
| `tenders` | 2 (Job 1) | **populated** (5 rows) | Active EU procurement notices polled from TED |
| `awards` | 2 (Job 2) | **populated** (5 rows) | Historic contract awards from TED — who won what |
| `companies` | 2 (Job 2) | **populated** (5 rows) | Canonical legal entities resolved from award winners |
| `documents` | 2 (Job 3) | empty | PDF tender dossiers (downloaded from `tenders.document_url`) |
| `company_profiles` | 5 | empty | Scraped capability profiles of vendors we pitch to |
| `matches` | 3 | empty | Tender × company scoring results |
| `emails` | 4 | empty | LLM-generated outreach drafts |
| `feedback` | 5 | empty | Thumbs-up/down ratings on emails (drives weight retraining) |
| `embeddings` | future | empty | Generic vector store for cross-model embeddings |
| `alembic_version` | meta | n/a | Tracks which migration is currently applied |

## Relationship map

The schema has **two disconnected sub-graphs** by design — there is no direct FK between them.

```
┌─ INGESTION (live now) ─────────────────────────────────────────────┐
│                                                                    │
│   tenders ──┐                          awards                      │
│   (int PK)  │                          (int PK)                    │
│             ├──> documents.tender_id   │                           │
│             │                          └──> companies.id           │
│             └──> matches.tender_id          (via winner_canonical_id)│
│                                                                    │
└────────────────────────────────────────────────────────────────────┘

┌─ MATCHING / EMAILS (Phase 3+, all empty) ──────────────────────────┐
│                                                                    │
│   matches ──┬──> company_profiles.id   ┌── emails.match_id         │
│   (UUID PK) │   (the demand side)      │                           │
│             └────────────────────────  ┘                           │
│                                                                    │
│   emails ───┬──> feedback.email_id                                 │
│             │                                                      │
│   matches ──┴──> feedback.match_id                                 │
│                                                                    │
│   embeddings (no FKs, stores vectors keyed by source_type+source_id)│
│                                                                    │
└────────────────────────────────────────────────────────────────────┘

```

### The roles of each table in matching

The mapping from "tenders + awards + scraping":

tenders — the demand side. Live procurement opportunities. Each row is "someone wants X built / X service supplied — bid by date Y". These are what we're matching for.
company_profiles (Phase 5, empty) — the supply side. The pool of vendors we pitch to. Each row will be a scraped capability profile (website, certifications, embedding). This is what tenders gets matched against. Web scraping populates this table, not tenders.

awards (Job 2, just populated) — historical signal, not the supply side. Tells us who has actually won past contracts in each CPV category. Two main uses:
Validate company_profiles: if a vendor we have in the pool has won similar contracts before, that's a strong positive signal.

Discover candidates: companies that consistently win in our target CPV categories are good additions to company_profiles.

So the matching pipeline is tenders × company_profiles → matches. awards informs the scoring but isn't a direct input.

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

### `tenders` — 5 rows, populated by Job 1

Source of all open EU procurement notices we want to match companies against. One row per TED Contract Notice (CN). Upserted by [poll_contract_notices()](../backend/app/ingestion/ted_client.py) keyed on `ted_notice_id`.

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

### `awards` — 5 rows, populated by Job 2

Historic contract awards. One row per TED Contract Award Notice (CAN) where a winner was selected. Notices that were cancelled-without-winner (`BT-142-LotResult = clos-nw`) are intentionally skipped at ingest time. Upserted by [backfill_awards()](../backend/app/ingestion/awards_client.py) keyed on `ted_notice_id`.

**Columns:**

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | autoincrement |
| `ted_notice_id` | varchar(64) | UNIQUE INDEX — upsert key (e.g. `82677-2026`) |
| `cpv_code` | varchar(32), nullable | First CPV from the notice (awards have many; we keep the primary) |
| `buyer_name` | text, nullable | The org that issued the procurement |
| `buyer_country` | varchar(8), nullable | ISO alpha-3 |
| `winner_raw_name` | text, **NOT NULL** | Winner name as TED returned it, pre-canonicalisation |
| `winner_canonical_id` | int, FK → `companies.id`, nullable | Set by `resolve_or_create` during ingest |
| `contract_value_eur` | float, nullable | Awarded contract value. **Note: `-1.0` is TED's "value withheld" sentinel** |
| `award_date` | date, nullable | Contract conclusion / winner decision date |
| `n_offers_received` | int, nullable | How many tenders were submitted for the winning lot |
| `raw_json` | json | Full original TED notice — preserved for evidence |
| `ingested_at` | timestamptz | When first inserted |

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

### `companies` — 5 rows, populated by Job 2 via entity resolution

Canonical legal entities, one row per unique winning organisation across all awards. Variant spellings ("Hochtief AG" / "Hochtief Aktiengesellschaft") collapse to one row via the normalised `resolution_key`. Populated by [entity_resolution.resolve_or_create()](../backend/app/ingestion/entity_resolution.py).

**Columns:**

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | autoincrement |
| `canonical_name` | text | UNIQUE INDEX — first raw name we saw for this entity |
| `resolution_key` | text | UNIQUE INDEX — normalised key used to dedupe variant spellings |
| `aliases` | json (list of str) | All raw names we've seen mapping to this entity |
| `country` | varchar(8), nullable | Inherited from the award's buyer (winner-country would be better — future improvement) |
| `created_at` | timestamptz | When this entity was first encountered |

**Normalisation logic** (in `normalise_name()`):
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

## Scaffold tables (empty until later phases)

These exist in the schema today but are populated by future jobs. Schemas are summarised for reference.

### `documents` — Phase 2 (Job 3, pending)

Will hold tender-dossier PDFs downloaded from `tenders.document_url`. One PDF per row, optionally with PyMuPDF-extracted text.

Columns: `id UUID PK`, `tender_id INTEGER FK→tenders.id`, `filename TEXT`, `storage_path TEXT`, `is_restricted BOOL`, `text_content TEXT`, `created_at`, `updated_at`.

`is_restricted = True` when the PDF lives behind a buyer portal that needs login (won't be auto-downloaded).

### `company_profiles` — Phase 5 (pending)

The **demand side** of matching. Distinct from `companies` — `company_profiles` will hold scraped capability profiles of vendors we want to pitch to (website, certifications, capabilities), with embeddings for semantic matching. Different lifecycle, different PK type (`UUID` to match `matches`).

Columns: `id UUID PK`, `name TEXT`, `country VARCHAR(8)`, `website TEXT`, `capabilities JSONB`, `certifications JSONB`, **`embedding Vector(384)`** (MiniLM-L6 dimension), `created_at`, `updated_at`.

### `matches` — Phase 3 (pending)

Result rows from the matching pipeline. One row per (`tender`, `company_profile`) pair the pipeline considered.

Columns: `id UUID PK`, `tender_id INT FK→tenders.id`, `company_id UUID FK→company_profiles.id`, four sub-scores (`semantic_score`, `budget_score`, `location_score`, `qualification_score`), `final_score FLOAT (idx)`, `weights JSONB` (the LR weights used), `explanation TEXT`, `is_disqualified BOOL`.

`final_score` is the sort key for ranked output.

### `emails` — Phase 4 (pending)

LLM-generated outreach drafts. One row per email sent (or scheduled).

Columns: `id UUID PK`, `match_id UUID FK→matches.id`, `subject TEXT`, `body TEXT`, `evidence JSONB` (extracted passages from `documents.text_content` that grounded the email), `status VARCHAR(32)` (default `'draft'`), `sent_at TIMESTAMPTZ`.

### `feedback` — Phase 5 (pending)

Captures thumbs-up/thumbs-down ratings teammates give on emails. Drives the LR weight retraining job.

Columns: `id UUID PK`, `match_id UUID FK`, `email_id UUID FK (nullable)`, `rating SMALLINT` (+1 or −1), `comment TEXT`.

### `embeddings` — future

Generic cross-model vector store, intentionally separate from `company_profiles.embedding` so we can store mpnet (768-dim) or multilingual-e5 (1024-dim) vectors alongside the 384-dim MiniLM ones without changing column types.

Columns: `id UUID PK`, `source_type VARCHAR(32) (idx)` (e.g. `'tender'`, `'company'`, `'document'`), `source_id UUID (idx)`, `model_name VARCHAR(64)`, **`vector Vector(768)`**.

### `alembic_version` — meta

Single-row table that records the migration head Alembic believes is applied. Today it should contain `0002_awards_companies`.

```sql
SELECT version_num FROM alembic_version;
-- 0002_awards_companies
```

If `alembic upgrade head` ever fails mid-migration, this row is what you check to see what state the DB thinks it's in.

---

## Migration history

| Revision | File | What it did |
|---|---|---|
| `0001_initial_schema` | [0001_initial_schema.py](../backend/app/db/migrations/versions/0001_initial_schema.py) | Created all 8 scaffold tables in one shot, plus `CREATE EXTENSION vector`. **Was edited in place during Job 1** to give `tenders` its final Job-1 shape (int PK, JSONB cpv_codes, etc.) before any production data existed — see [docs/architecture.md](architecture.md) for the rationale. |
| `0002_awards_companies` | [0002_awards_companies.py](../backend/app/db/migrations/versions/0002_awards_companies.py) | **Additive** — dropped the scaffold `awards` table (UUID PK, FK to tenders) and recreated it with the Job 2 shape (int PK, `winner_canonical_id` FK to new `companies` table). Created `companies`. Preserves Job 1 tender rows. |

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

## Future roadmap (Phase 3+)

In rough order of when each scaffold table comes online:

1. **Job 3 — dossier downloader** populates `documents`. PDFs fetched from `tenders.document_url`, PyMuPDF extracts text into `documents.text_content`. Phase 2.
2. **Job 4 — APScheduler loop** runs Jobs 1–3 on a schedule (daily tender poll, weekly awards back-fill, dossier download on insert).
3. **Phase 3 — matching engine** populates `company_profiles` (initially seeded by hand from a curated vendor list), then runs the `MatchingPipeline` to compute sub-scores and write `matches` rows. The sub-scores are weighted by an LR model whose weights live in `matches.weights`.
4. **Phase 4 — generation** picks high-`final_score` matches, drafts emails via Claude tool-use grounded in `documents.text_content`, writes to `emails`.
5. **Phase 5 — feedback loop** captures thumbs-up/down via `feedback`, retrains the LR weights from accumulated signal, refreshes `company_profiles.embedding` periodically. Also where multi-tenant auth lands.

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
