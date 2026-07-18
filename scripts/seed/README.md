# Demo seed

A small, **referentially-consistent slice of real dev data** (~2.3 MB) so the
whole UI shows real content on a fresh database — without running a slow,
network-dependent TED ingestion first. Intended for a reviewer who wants to
**boot the app once and look around**.

## Load it

Prereqs: the DB container is up and the schema has been migrated.

```bash
docker compose up -d db          # start Postgres
cd backend && alembic upgrade head && cd ..   # create the schema (0001 → 0015)

# then load the seed (pick your shell):
./scripts/seed/load_seed.sh                     # macOS / Linux / Git Bash
#   or
powershell -File scripts\seed\load_seed.ps1     # Windows PowerShell
```

Both helpers load with `ON_ERROR_STOP=1` in a byte-safe way (the bash script
streams the file to `psql` over stdin; the PowerShell script `docker cp`s it in
and runs `psql -f`), so the multilingual company/tender text isn't re-encoded.
Default container name is `gtmagent-db-1`; pass another as the first argument /
`-Container` if yours differs (`docker ps` to check).

Load into an **empty** post-migration database. Loading on top of existing rows
will fail on primary-key conflicts (by design — it's a seed, not an upsert).

## What's in it

| Table | Rows | Slice |
|---|---:|---|
| tenders | 166 | the 13 that have matches + ~150 recent, for a browsable list |
| matches | 236 | up to 20 top matches per matched tender (+ any referenced by emails/feedback) |
| company_profiles | 231 | exactly the supplier profiles those matches point at |
| companies | 231 | the canonical companies behind those profiles |
| awards | 471 | award history of those companies (drives the Companies/Awards views) |
| emails | 6 | generated supplier/buyer drafts |
| tender_reports | 5 | saved agent analyses (narrative + supplier snapshot) |
| documents / feedback / reflections | 5 / 3 / 1 | as-is |

Every foreign-key parent of every seeded row is included, so it loads clean into
the migrated schema (verified with `ON_ERROR_STOP=1` + orphan checks).

**Caveat:** the bulky `raw_json` TED payloads are replaced with a small
placeholder to keep the seed ~2 MB (they're only shown in the detail-panel "raw
payload" view — nothing functional reads them). Re-ingest from TED for full
payloads.

## Regenerate it

From a populated dev DB (with the backend venv active):

```bash
python scripts/seed/generate_seed.py    # rewrites seed_demo.sql
```

The generator (`generate_seed.py`) computes the slice server-side as the
transitive FK closure over the matched tenders — see its module docstring.
