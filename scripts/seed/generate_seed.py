"""Generate a curated demo seed (scripts/seed/seed_demo.sql) from a populated dev DB.

Why this exists
---------------
`docker compose up` gives a checker an *empty* database — to see the app populated
they'd otherwise have to run a slow, network-dependent TED ingestion. This script
extracts a small, **referentially-consistent slice** of the real dev data so the
whole UI (tenders, matches, companies, awards, emails, saved reports) shows real
content after a one-line load. See scripts/seed/README.md for how to load it.

What the slice contains
-----------------------
Only the demo-worthy core, with every foreign-key parent guaranteed present:
  * the tenders that actually have matches (+ a few recent ones to browse),
  * up to 20 top matches per matched tender (+ any referenced by emails/feedback),
  * exactly the company_profiles / companies / awards those matches point at,
  * all emails, feedback, saved tender_reports, documents, reflections (tiny).
The pool tables in full (~21k awards / ~15k company_profiles) are far too large to
ship, so we take their transitive closure over the seeded matches instead.

Run (from repo root, with the dev DB up and the backend venv active):
    python scripts/seed/generate_seed.py
Override the source DB via env if needed:
    SEED_HOST / SEED_PORT / SEED_DB / SEED_USER / SEED_PASSWORD
"""
from __future__ import annotations

import os
from pathlib import Path

import psycopg

OUT_PATH = Path(__file__).parent / "seed_demo.sql"

# ── Reusable closure subqueries (kept as SQL text so all the set logic runs
# ── server-side — we never marshal id lists through Python). Order matters only
# ── for readability; Postgres resolves the nesting. ─────────────────────────────
SEED_MATCH_IDS = """(
    SELECT id FROM (
        SELECT id, row_number() OVER (
            PARTITION BY tender_id ORDER BY final_score DESC NULLS LAST
        ) AS rn
        FROM matches
    ) ranked WHERE rn <= 20
    UNION SELECT match_id FROM emails WHERE match_id IS NOT NULL
    UNION SELECT match_id FROM feedback WHERE match_id IS NOT NULL
)"""

SEED_TENDER_IDS = """(
    SELECT DISTINCT tender_id FROM matches
    UNION SELECT tender_id FROM tender_reports WHERE tender_id IS NOT NULL
    UNION SELECT tender_id FROM documents WHERE tender_id IS NOT NULL
    UNION SELECT tender_id FROM emails WHERE tender_id IS NOT NULL
    UNION (SELECT id FROM tenders ORDER BY ingested_at DESC NULLS LAST LIMIT 150)
)"""

SEED_PROFILE_IDS = f"(SELECT DISTINCT company_id FROM matches WHERE id IN {SEED_MATCH_IDS})"

SEED_COMPANY_IDS = (
    f"(SELECT DISTINCT source_company_id FROM company_profiles "
    f"WHERE id IN {SEED_PROFILE_IDS} AND source_company_id IS NOT NULL)"
)

# The full TED payload (`raw_json`, avg ~10-13 KB/row) is only shown in the
# tender/award *detail* inspection panel — nothing functional reads it — so we
# replace it with a small placeholder to keep the seed ~2 MB instead of ~10 MB.
# Re-ingest from TED for the real payloads.
TRIM_RAWJSON = (
    "'{\"_seed\":\"raw_json omitted from the demo seed to keep it small; "
    "re-ingest from TED for the full payload\"}'::json"
)

# ── Per-table extraction, in FK-safe insert order (parents before children). ────
# Each entry: (table, WHERE/limit clause, {column: sql_override}).
# `session_id` on tender_reports is FK→agent_sessions, which we don't seed, so we
# emit NULL for it (the FK is ON DELETE SET NULL — nullable by design).
TABLES: list[tuple[str, str, dict[str, str]]] = [
    ("companies", f"WHERE id IN {SEED_COMPANY_IDS} ORDER BY id", {}),
    ("tenders", f"WHERE id IN {SEED_TENDER_IDS} ORDER BY id", {"raw_json": TRIM_RAWJSON}),
    ("company_profiles", f"WHERE id IN {SEED_PROFILE_IDS} ORDER BY id", {}),
    ("awards",
     f"WHERE winner_canonical_id IN {SEED_COMPANY_IDS} "
     f"ORDER BY contract_value_eur DESC NULLS LAST, id LIMIT 1500", {"raw_json": TRIM_RAWJSON}),
    ("matches", f"WHERE id IN {SEED_MATCH_IDS} ORDER BY id", {}),
    ("documents", f"WHERE tender_id IN {SEED_TENDER_IDS} ORDER BY id", {}),
    ("emails", f"WHERE match_id IN {SEED_MATCH_IDS} ORDER BY id", {}),
    ("feedback", f"WHERE match_id IN {SEED_MATCH_IDS} ORDER BY id", {}),
    ("tender_reports",
     f"WHERE tender_id IN {SEED_TENDER_IDS} ORDER BY id",
     {"session_id": "NULL"}),
    ("reflections", "ORDER BY id", {}),
]


def conninfo() -> str:
    return (
        f"host={os.environ.get('SEED_HOST', 'localhost')} "
        f"port={os.environ.get('SEED_PORT', '5432')} "
        f"dbname={os.environ.get('SEED_DB', 'gtm')} "
        f"user={os.environ.get('SEED_USER', 'gtm')} "
        f"password={os.environ.get('SEED_PASSWORD', 'gtm')}"
    )


def columns(cur: psycopg.Cursor, table: str) -> list[str]:
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
        (table,),
    )
    return [r[0] for r in cur.fetchall()]


def main() -> None:
    header = (
        "-- GTMAgent demo seed — GENERATED by scripts/seed/generate_seed.py, do not hand-edit.\n"
        "-- A small, referentially-consistent slice of real dev data so the UI shows\n"
        "-- real content on a fresh DB. Load AFTER `alembic upgrade head` into an empty\n"
        "-- database (see scripts/seed/README.md).\n\n"
        "BEGIN;\n"
        "-- Defer FK/trigger checks while bulk-loading (rows are FK-ordered anyway).\n"
        "SET session_replication_role = replica;\n\n"
    )
    footer = "\nSET session_replication_role = origin;\nCOMMIT;\n"

    counts: dict[str, int] = {}
    with psycopg.connect(conninfo()) as conn, conn.cursor() as cur:
        with open(OUT_PATH, "wb") as f:
            f.write(header.encode())
            for table, where, overrides in TABLES:
                cols = columns(cur, table)
                col_list = ", ".join(cols)
                select_exprs = ", ".join(overrides.get(c, c) for c in cols)
                cur.execute(f"SELECT count(*) FROM (SELECT id FROM {table} {where}) s")
                counts[table] = cur.fetchone()[0]
                f.write(f"COPY public.{table} ({col_list}) FROM stdin;\n".encode())
                copy_sql = f"COPY (SELECT {select_exprs} FROM {table} {where}) TO STDOUT"
                with cur.copy(copy_sql) as cp:
                    while data := cp.read():
                        f.write(data)
                f.write(b"\\.\n\n")
            f.write(footer.encode())

    total = sum(counts.values())
    print(f"Wrote {OUT_PATH} ({OUT_PATH.stat().st_size // 1024} KB, {total} rows)")
    for t, n in counts.items():
        print(f"  {t:16} {n}")


if __name__ == "__main__":
    main()
