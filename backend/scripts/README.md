# backend/scripts

Diagnostic + maintenance scripts for the backend. Intentionally separate from `backend/app/` — these are operator tools, not part of the runtime package.

Current contents:

| File | Purpose |
|---|---|
| `ted_smoke.py` | TED v3 ingestion smoke test (Job 1) — exercises the live API and (optionally) writes to the `tenders` table |
| `awards_smoke.py` | TED Award (CAN) back-fill smoke test (Job 2) — exercises the live API and (optionally) writes to the `awards` + `companies` tables |
| `agent_smoke.py` | Claude tool-use agent smoke test (Phase 6) — runs `AgentController` against a goal (dry-run by default) |

> **For routine ingestion, prefer the unified CLI** over the smoke scripts:
> `python -m app.ingestion --mode {contracts,awards,both} [--no-dossiers] [--dry-run] [--limit N]`
> (run from `backend/`). The smoke scripts are diagnostic tools — they add a raw
> API "peek" phase and richer per-notice logging for debugging field-mapping
> surprises. There is no dedicated matching smoke script yet; to exercise the
> matching pipeline end-to-end, use the copy-paste reproduction snippet in
> [archive/internal-logs/matching_pipeline_smoke_record.md](../../archive/internal-logs/matching_pipeline_smoke_record.md)
> or the API (`POST /api/v1/matches/run/{tender_id}`).

---

## One-time test database setup

The DB-touching tests in `backend/tests/ingestion/test_dossier_downloader.py` (and any future tests that use the `db_session` fixture from `backend/tests/conftest.py`) need a separate Postgres database named `gtm_test`. This is intentional — tests freely `CREATE`, `DROP`, and roll back transactions on it, and we don't want that anywhere near your dev data.

The fixtures don't auto-create the database itself (Postgres doesn't allow `CREATE DATABASE` inside a transaction, and we'd need elevated permissions). One-time setup, with the dev container running:

```powershell
docker exec gtmagent-db-1 psql -U gtm -d gtm -c "CREATE DATABASE gtm_test;"
docker exec gtmagent-db-1 psql -U gtm -d gtm_test -c "CREATE EXTENSION vector;"
```

After that, the test fixtures handle everything (schema create/drop, per-test rollback). Verify with:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests/ingestion/test_dossier_downloader.py -v
```

You should see 14 tests pass. If the suite errors out with `database "gtm_test" does not exist`, you missed the `CREATE DATABASE` step above.

The connection string is configurable via `DATABASE_URL_TEST` in `backend/.env` if you want to point at a different host/db — default is `postgresql+psycopg://gtm:gtm@localhost:5432/gtm_test`.

---

## Least-privilege role for the agent `query_db` tool (P2 hardening)

The app connects as `gtm`, which the pgvector image creates as a **superuser**. The agent's read-only `query_db` tool is guarded at the app layer (single `SELECT`, dangerous-function blocklist, statement timeout), but the *structural* guarantee is to run those queries under a dedicated non-superuser, read-only role so Postgres itself refuses file access (`pg_read_file`), credential reads (`pg_authid`), and writes — regardless of the app guard.

One-time provisioning, with the dev container running:

```powershell
docker exec -i gtmagent-db-1 psql -U gtm -d gtm < backend\scripts\create_readonly_role.sql
```

Then point the app at the role by adding to `backend/.env`:

```
DATABASE_URL_READONLY=postgresql+psycopg://gtm_ro:gtm_ro@localhost:6543/gtm
```

Restart the backend. `query_db` now runs on the `gtm_ro` connection; everything else keeps using `gtm`. **When `DATABASE_URL_READONLY` is unset (the default), `query_db` falls back to the guarded shared session** — still safe via the app-layer guard + timeout, just without the DB-level guarantee. So this is opt-in and dev/CI/tests are unaffected.

Verify the role is correctly locked down (all but the first should be **denied**):

```powershell
docker exec gtmagent-db-1 psql -U gtm_ro -d gtm -c "SELECT count(*) FROM tenders;"          # OK
docker exec gtmagent-db-1 psql -U gtm_ro -d gtm -c "SELECT pg_read_file('/etc/passwd');"     # permission denied
docker exec gtmagent-db-1 psql -U gtm_ro -d gtm -c "SELECT rolpassword FROM pg_authid;"      # permission denied
docker exec gtmagent-db-1 psql -U gtm_ro -d gtm -c "CREATE TABLE x (i int);"                 # read-only transaction
```

---

## ted_smoke.py

End-to-end exerciser for the Phase 2 / Job 1 TED Contract Notice poller. Useful for:

- Verifying the live TED API is reachable and returning data
- Confirming our query syntax + body fields still get HTTP 200
- Seeing exactly what shape TED responses take (handy for understanding field mapping)
- Smoke-testing the insert/upsert path after schema changes or migrations

It runs in two phases (either can be skipped via flags):

**Phase 1 — PEEK**: one `TedClient.search()` call. Dumps the response's top-level keys, the first notice's keys, and a 2KB-truncated JSON of the first notice. No DB activity. Useful for "what does today's TED response actually look like?"

**Phase 2 — POLL**: `poll_contract_notices()` end-to-end. Defaults to `dry_run=True` (parses everything, writes nothing). Pass `--live` to flip `dry_run=False` and actually upsert into `tenders`.

### Prerequisites

The same prereqs as the rest of the backend (see the [root README](../../README.md#prerequisites)):

- Docker Desktop running with the project's `gtmagent-db-1` container up
- Python 3.11 venv at `backend/.venv` with `pip install -r backend/requirements-dev.txt`
- `backend/.env` populated (the script chdirs to `backend/` internally so Settings finds it)

Quick prerequisite check:

```powershell
docker ps --filter "name=gtm" --format "table {{.Names}}\t{{.Status}}"
# Expected: gtmagent-db-1   Up X minutes (healthy)
```

If the container isn't up: `docker compose up -d db` from the repo root.

### Running

From the **repo root** (`c:\dev\GTMAgent`) with the venv active:

```powershell
# Default — both phases, dry-run, days=3, limit=5, verbose
python backend\scripts\ted_smoke.py

# Just see the raw API shape (no DB activity)
python backend\scripts\ted_smoke.py --no-dry-run

# Write 5 rows to the tenders table (idempotent — re-run gives 5 updates)
python backend\scripts\ted_smoke.py --live --limit 5 --no-peek

# Wider window for testing pagination
python backend\scripts\ted_smoke.py --days 30 --limit 200 --no-peek
```

### Flags

| Flag | Default | Effect |
|---|---|---|
| `--cpv 45000000-7,72000000-5` | from `.env` `ALLOWED_CPV_CODES` | Override CPV scope (comma-separated). EU check-digit suffix is stripped before sending. |
| `--days N` | `3` | Polling window: `publication-date >= today - N days` |
| `--limit N` | `5` | Max notices to consume across all pages |
| `--no-peek` | off | Skip Phase 1 (the raw response dump) |
| `--no-dry-run` | off | Skip Phase 2 (the poll) — useful with `--no-peek` to do neither, but mostly used with phase 1 only |
| `--live` | off | **Phase 2 writes to DB.** Without this flag, Phase 2 parses notices but does not touch `tenders`. |
| `--quiet` | off | Suppress per-notice INFO logs in Phase 2 |

### Reading the output

Phase 1 should print something like:

```
--- PHASE 1: raw peek (limit=5) ---
QUERY: notice-type IN (cn-standard, cn-social) AND classification-cpv IN (45000000, 72000000) AND publication-date >= 20260513
2026-05-16 09:28:52 INFO httpx HTTP Request: POST https://api.ted.europa.eu/v3/notices/search "HTTP/1.1 200 OK"
RESPONSE TOP-LEVEL KEYS: ['iterationNextToken', 'notices', 'timedOut', 'totalNoticeCount']
Found 5 notices under key 'notices'
First notice keys: ['BT-131(d)-Lot', 'BT-21-Procedure', ..., 'publication-number']
First notice (truncated):
{ ... }
```

Phase 2 should end with:

```
2026-05-16 09:28:52 INFO app.ingestion.ted_client Poll complete: 5 fetched, 0 new, 0 updated, 0 errors
SUMMARY: {'fetched': 5, 'new': 0, 'updated': 0, 'errors': 0}
```

In `--live` mode, `new` + `updated` should sum to `fetched`. First live run on a fresh DB: `new = fetched`. Second run with the same notices: `updated = fetched` and `new = 0`.

### What to do if it fails

- **HTTP 400 Bad Request**: The script prints the full TED error body in Phase 1 (a wrapper around `_peek` catches `HTTPStatusError`). Read the `error.type` and `unsupportedValue` fields to see exactly what TED rejected.
- **HTTP 200 but "NO LIST FOUND under expected keys"**: the response envelope shape changed. Update `_iter_notices` in [backend/app/ingestion/ted_client.py](../app/ingestion/ted_client.py).
- **`CERTIFICATE_VERIFY_FAILED`**: Local SSL trust issue (AV / corporate proxy intercepting TLS). The `truststore` package wired into `TedClient` should already handle this; if it doesn't, check that `truststore==0.10.4` is installed in the venv.
- **`ConnectError` to api.ted.europa.eu**: Try `--no-peek --no-dry-run` to confirm script wiring; check internet reachability. The TedClient also retries once on `tedweb.api.ted.europa.eu/v3/...` automatically.

---

## awards_smoke.py

End-to-end exerciser for the Phase 2 / Job 2 TED Award (CAN) back-fill. Same two-phase shape as `ted_smoke.py`:

**Phase 1 — PEEK**: one `TedClient.search()` call with the awards query (`notice-type IN (can-standard, can-social, can-desg)`). Dumps response top-level keys, the first notice's keys, and a 2KB-truncated JSON of the first notice. No DB activity.

**Phase 2 — DRY-RUN / LIVE**: `backfill_awards()` end-to-end. Defaults to `dry_run=True` (parses everything, opens no DB session). Pass `--live` to flip `dry_run=False` and actually upsert into `awards` + resolve winners into `companies`.

### Prerequisites

Same prereqs as `ted_smoke.py` (Docker DB up, venv populated, `.env` present). Additionally, **migration `0002_awards_companies` must be applied** before any `--live` run — otherwise the inserts will fail against the scaffold `awards` shape from `0001`:

```powershell
cd backend
.\.venv\Scripts\alembic.exe upgrade head
```

### Running

From the **repo root** (`c:\dev\GTMAgent`) with the venv active:

```powershell
# Default — both phases, dry-run, months=24, limit=5, verbose
python backend\scripts\awards_smoke.py

# Just see the raw API shape (no DB activity)
python backend\scripts\awards_smoke.py --no-dry-run

# Write 5 award rows + resolve their winners (idempotent — re-run gives 5 updates)
python backend\scripts\awards_smoke.py --live --limit 5 --no-peek

# Shorter window for faster iteration
python backend\scripts\awards_smoke.py --months 6 --limit 20
```

### Flags

| Flag | Default | Effect |
|---|---|---|
| `--cpv 45000000-7,72000000-5` | from `.env` `ALLOWED_CPV_CODES` | Override CPV scope. Check-digit suffix stripped before sending. |
| `--months N` | `24` (from `Settings.awards_backfill_months`) | Back-fill window: `publication-date >= today - (N × 30) days` |
| `--limit N` | `5` | Max notices to consume across all pages |
| `--no-peek` | off | Skip Phase 1 |
| `--no-dry-run` | off | Skip Phase 2 |
| `--live` | off | **Phase 2 writes to DB.** Without this flag, Phase 2 parses notices but opens no DB session. |
| `--quiet` | off | Suppress per-notice INFO logs in Phase 2 |

### Reading the output

Phase 2 should end with:

```
INFO app.ingestion.awards_client Backfill complete: 5 fetched, 5 new, 0 updated, 4 companies, 0 errors
SUMMARY: {'fetched': 5, 'new': 5, 'updated': 0, 'companies_created': 4, 'errors': 0}
```

`companies_created` ≤ `new` because winner-name dedup happens at insert time — if two awards have the same winner (e.g. "Hochtief AG" and "Hochtief Aktiengesellschaft"), the second resolves to the existing `companies` row.

### What to do if it fails

- **HTTP 400 with "Value 'can-desg' is not supported"** (or `'can-social'`): mirrors the Job 1 `cn-light` lesson. Edit `NOTICE_TYPES` in [backend/app/ingestion/awards_client.py](../app/ingestion/awards_client.py) — drop the rejected value and re-run. The smoke script prints a HINT to this effect when it sees `can-desg` or `can-social` in the error body.
- **HTTP 400 with "Value 'BT-720-Lot-Tender-Value' is not supported"** (or any other field name): the TED docs vs. live API mismatch from Job 1 is back. Edit `AWARD_FIELDS` in the same file, drop the offending field, re-run.
- **Phase 2 returns `fetched=0` with no errors**: the query matched nothing in the window. Try `--months 36` or a different `--cpv`.
- **`UndefinedTable: relation "companies" does not exist`** on `--live`: migration `0002` hasn't been applied yet. Run `alembic upgrade head` (from `backend/`).
- **`ForeignKeyViolation` on `awards.winner_canonical_id`**: shouldn't happen — `_process_notice_persistent` flushes the `Company` insert before referencing its id. If it does, the savepoint pattern is broken; check that `session.flush()` runs inside the `begin_nested()` block.
- Same `CERTIFICATE_VERIFY_FAILED` / `ConnectError` failure modes as Phase 1 of `ted_smoke.py` — see above.

---

## Inspecting what got written — DB query cheatsheet

After a `--live` run, here are copy-paste queries for inspecting the `tenders` table from the Docker container. Run any of these from your shell.

### Row counts across all tables

```powershell
docker exec -it gtmagent-db-1 psql -U gtm -d gtm -c "SELECT 'tenders' AS t, count(*) FROM tenders UNION ALL SELECT 'awards', count(*) FROM awards UNION ALL SELECT 'companies', count(*) FROM companies UNION ALL SELECT 'company_profiles', count(*) FROM company_profiles UNION ALL SELECT 'documents', count(*) FROM documents UNION ALL SELECT 'matches', count(*) FROM matches UNION ALL SELECT 'emails', count(*) FROM emails UNION ALL SELECT 'feedback', count(*) FROM feedback UNION ALL SELECT 'embeddings', count(*) FROM embeddings ORDER BY 1;"
```

Tells you which tables have data. After Job 1, only `tenders` should be populated. After Job 2 (`awards_smoke.py --live`), `awards` and `companies` will be populated too.

### Show schema of the tenders table

```powershell
docker exec -it gtmagent-db-1 psql -U gtm -d gtm -c "\d tenders"
```

Lists every column with its type, nullability, default, and indexes/FKs referencing it. Best one-shot view of what the table looks like.

### List all rows with key parsed columns

```powershell
docker exec -it gtmagent-db-1 psql -U gtm -d gtm -c "SELECT ted_notice_id, buyer_country, deadline::date, substr(title, 1, 60) FROM tenders;"
```

Quick scan: did we get notices from a variety of countries? Are deadlines sensible? Are titles populated?

### Full raw JSON for one notice (pretty-printed)

```powershell
docker exec -it gtmagent-db-1 psql -U gtm -d gtm -c "SELECT jsonb_pretty(raw_json) FROM tenders WHERE ted_notice_id = '326612-2026';"
```

Swap the `ted_notice_id` for any value you saw in the previous query. This is the **complete original TED notice** — every field TED returned, including ones we don't surface in dedicated columns yet. Useful when designing future jobs (the matcher and drafter will mine this for evidence).

### Side-by-side: parsed columns vs. raw fields they came from

```powershell
docker exec -it gtmagent-db-1 psql -U gtm -d gtm -c "SELECT ted_notice_id AS parsed_id, raw_json->>'publication-number' AS raw_id, title AS parsed_title, raw_json->'BT-21-Procedure' AS raw_BT21, buyer_country AS parsed_country, raw_json->'buyer-country' AS raw_country, cpv_codes AS parsed_cpvs, raw_json->'classification-cpv' AS raw_cpvs FROM tenders WHERE ted_notice_id = '326612-2026';"
```

Documents the field mapping in actual data — useful for understanding how `from_ted_response` translates each TED key into our schema. The mapping logic lives in [backend/app/ingestion/schemas.py](../app/ingestion/schemas.py).

### Verify the upsert path bumped updated_at correctly

```powershell
docker exec -it gtmagent-db-1 psql -U gtm -d gtm -c "SELECT ted_notice_id, ingested_at, updated_at, ingested_at < updated_at AS was_updated FROM tenders ORDER BY ted_notice_id;"
```

After two consecutive `--live` runs, all rows should show `was_updated = t`. After the first run, all should be `f`.

### Export one row's raw JSON to a file for browsing in your editor

```powershell
docker exec gtmagent-db-1 psql -U gtm -d gtm -t -A -c "SELECT jsonb_pretty(raw_json) FROM tenders WHERE ted_notice_id = '326612-2026';" > c:\dev\GTMAgent\backend\storage\sample_326612.json
```

Then open `backend\storage\sample_326612.json` in VS Code. The `-t -A` flags strip psql's header/borders for clean JSON output.

### Truncate the table (start fresh)

```powershell
docker exec -it gtmagent-db-1 psql -U gtm -d gtm -c "TRUNCATE tenders RESTART IDENTITY CASCADE;"
```

Wipes all rows and resets the autoincrement counter. `CASCADE` follows FKs into `documents`/`matches` (Job 2's `awards` table is NOT a child of `tenders` and won't be touched).

---

## Awards + companies (Job 2)

After a `--live` run of `awards_smoke.py`, here are the parallel queries for the new tables.

### Show schema

```powershell
docker exec -it gtmagent-db-1 psql -U gtm -d gtm -c "\d awards"
docker exec -it gtmagent-db-1 psql -U gtm -d gtm -c "\d companies"
```

### Join awards to their resolved winners

```powershell
docker exec -it gtmagent-db-1 psql -U gtm -d gtm -c "SELECT a.ted_notice_id, c.canonical_name AS winner, a.buyer_country, a.contract_value_eur, a.award_date FROM awards a LEFT JOIN companies c ON c.id = a.winner_canonical_id ORDER BY a.award_date DESC NULLS LAST LIMIT 20;"
```

Quick scan: did each award resolve to a `companies` row? Are buyer countries plausible? Are contract values populated for most rows?

### See the winner-dedup in action

```powershell
docker exec -it gtmagent-db-1 psql -U gtm -d gtm -c "SELECT canonical_name, resolution_key, jsonb_array_length(aliases::jsonb) AS n_aliases, aliases FROM companies WHERE jsonb_array_length(aliases::jsonb) > 1 ORDER BY n_aliases DESC;"
```

Lists companies that have more than one alias — i.e. cases where `resolve_or_create` collapsed variant spellings ("Hochtief AG" + "Hochtief Aktiengesellschaft") into one row.

### Find awards where winner resolution didn't run

```powershell
docker exec -it gtmagent-db-1 psql -U gtm -d gtm -c "SELECT ted_notice_id, winner_raw_name FROM awards WHERE winner_canonical_id IS NULL;"
```

Should be empty after a clean `--live` run. Non-empty means a row landed without the entity-resolution savepoint completing — investigate the log for `Failed to upsert award notice id=...`.

### Truncate awards + companies (start fresh)

```powershell
docker exec -it gtmagent-db-1 psql -U gtm -d gtm -c "TRUNCATE awards, companies RESTART IDENTITY CASCADE;"
```

Both tables together so the FK doesn't trip. `tenders` is untouched.

### Drop the database entirely (nuclear option)

```powershell
docker compose down -v          # wipes the pgdata volume
docker compose up -d db
cd backend
alembic upgrade head            # rebuild schema at current head (0015)
```

Use when migrations get tangled (e.g. after switching branches with a different migration head).

---

## GUI alternatives

If you prefer point-and-click over psql:

| Tool | Pros |
|---|---|
| **DBeaver** (free desktop) | Free, cross-platform, expand JSONB cells inline by clicking `...` or `Shift+Enter`. Connect: host `localhost`, port `5432`, db `gtm`, user `gtm`, password `gtm`. |
| **pgAdmin** (free desktop) | Reference PG GUI; heavier UI. Same connection params. |
| **Adminer** (in-container web GUI) | Not currently in `docker-compose.yml`. Ask if you want it added. |

---

## Adding new scripts here

When adding another diagnostic / maintenance script:

- Make it self-contained — `os.chdir(ROOT)` near the top so `backend/.env` loads regardless of where the script is invoked from
- Use `argparse` for any tunable flags (window size, limit, dry-run toggle)
- Log via the standard `logging` module — not `print()` — and call `logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")` once at the top of `main()`
- Document it in this README with a flag table + sample output
- Keep destructive operations (writes, truncates) behind an explicit flag like `--live` so accidental invocation is harmless

---

## agent_smoke.py

End-to-end exerciser for the ReAct Agent Controller (`AgentController`). Exercises the Anthropic API loop and confirms exactly how the agent translates a query into a sequence of tool dispatches. 

Useful for:
- Validating your `ANTHROPIC_API_KEY` configuration.
- Verifying the `messages` and `tools` schema definitions conform properly to Anthropic's Tool Use API strict validation requirements.
- Inspecting exactly what the agent decides to invoke to accomplish a task.

### Prerequisites

You need a valid `ANTHROPIC_API_KEY` loaded in `backend/.env`.

### Running

From the **repo root** (`c:\dev\GTMAgent`) with the venv active:

```powershell
# Default prompt
python backend\scripts\agent_smoke.py

# Custom goal
python backend\scripts\agent_smoke.py --goal "Can you search the database for IT services tenders?"

# Quiet mode (only final output)
python backend\scripts\agent_smoke.py --quiet
```

### Flags

| Flag | Default | Effect |
|---|---|---|
| `--goal "... text ..."` | default test objective | The instruction provided to the Agent. |
| `--live` | off | **Allows the caged ingest tools to reach the network for real.** Without this flag (the default), `AgentController(dry_run=True)` makes `ingest_tenders` / `ingest_awards` report what they *would* do — dry-run means **no network at all**, not merely no DB writes. Pass `--live` to flip `dry_run=False` and allow real TED polls / DB writes as a side effect of whatever plan the model comes up with; even then, live ingests stay bounded and run at most once per agent run. |
| `--quiet` | off | Suppress Python logging, outputting only the Agent's final text payload. |

**Safety note**: a chat-style goal like "find me a recent German tender" can
cause the model to *plan* a live ingestion as a side effect.
`dry_run=True` (the default for both this script and the `/api/v1/agent/run`
endpoint) is what keeps that safe to experiment with — only pass `--live`
when you actually want the agent to write to the DB / hit the TED API.

### Reading the output

You should see log outputs detailing initial API dispatch followed by:

```
2026-05-31 10:15:00 INFO __main__ === Agent Run Complete ===
2026-05-31 10:15:00 INFO __main__ Tool Steps Taken: 1
2026-05-31 10:15:00 INFO __main__   [1] Tool: query_db | Args: {'sql_query': 'SELECT * FROM tenders;'}
2026-05-31 10:15:00 INFO __main__ === Final Agent Output ===

I have searched the available records based on your parameters...
```
