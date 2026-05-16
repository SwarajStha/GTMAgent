"""TED ingestion smoke test (dry-run, no DB writes).

Two phases:
  1) PEEK     one TedClient.search() call; dump response top-level keys
              and the first notice so we can sanity-check shape + query.
  2) DRY-RUN  poll_contract_notices(dry_run=True) end-to-end; print the
              fetched/new/updated/errors summary.

Run from anywhere; the script chdirs to backend/ so Settings loads .env.

Usage (from c:\\dev\\GTMAgent\\backend):
  .\\.venv\\Scripts\\python.exe .\\scripts\\ted_smoke.py
  .\\.venv\\Scripts\\python.exe .\\scripts\\ted_smoke.py --days 7 --limit 10
  .\\.venv\\Scripts\\python.exe .\\scripts\\ted_smoke.py --cpv 45000000-7 --no-peek
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import get_settings  # noqa: E402
from app.ingestion.base_client import TedClient  # noqa: E402
from app.ingestion.ted_client import (  # noqa: E402
    TED_FIELDS,
    _build_query,
    poll_contract_notices,
)


def _peek(query: str, limit: int) -> None:
    print(f"\n--- PHASE 1: raw peek (limit={limit}) ---")
    print(f"QUERY: {query}")
    try:
        with TedClient() as client:
            page = client.search(query=query, fields=TED_FIELDS, page=1, limit=limit)
    except httpx.HTTPStatusError as e:
        print(f"\nHTTP {e.response.status_code} — FULL RESPONSE BODY:\n")
        print(e.response.text)
        raise
    print(f"RESPONSE TOP-LEVEL KEYS: {sorted(page.keys())}")
    for key in ("notices", "results", "items", "data"):
        v = page.get(key)
        if isinstance(v, list):
            print(f"Found {len(v)} notices under key {key!r}")
            if v:
                print(f"First notice keys: {sorted(v[0].keys())}")
                print(f"First notice (truncated):\n{json.dumps(v[0], indent=2)[:2000]}")
            return
    print("NO LIST FOUND under expected keys. Full response (truncated):")
    print(json.dumps(page, indent=2)[:2000])


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cpv", help="Comma-separated CPVs (default: .env ALLOWED_CPV_CODES)")
    p.add_argument("--days", type=int, default=3)
    p.add_argument("--limit", type=int, default=5)
    p.add_argument("--no-peek", action="store_true", help="Skip phase 1")
    p.add_argument("--no-dry-run", action="store_true", help="Skip phase 2")
    p.add_argument(
        "--live",
        action="store_true",
        help="Flip phase 2 to dry_run=False — writes rows to the tenders table",
    )
    p.add_argument("--quiet", action="store_true", help="Suppress per-notice INFO logs")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    settings = get_settings()
    cpv = [c.strip() for c in args.cpv.split(",")] if args.cpv else settings.cpv_code_list
    if not cpv:
        print("No CPV codes resolved. Set --cpv or ALLOWED_CPV_CODES in backend/.env.")
        return 2

    if not args.no_peek:
        try:
            _peek(_build_query(cpv, args.days), args.limit)
        except Exception:
            logging.exception("Peek phase failed")
            return 1

    if not args.no_dry_run:
        mode = "LIVE (writes DB)" if args.live else "dry-run"
        print(f"\n--- PHASE 2: {mode} poll (days={args.days}, limit={args.limit}) ---")
        summary = poll_contract_notices(
            cpv_codes=cpv,
            days=args.days,
            dry_run=not args.live,
            limit=args.limit,
            verbose=not args.quiet,
        )
        print(f"\nSUMMARY: {summary}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
