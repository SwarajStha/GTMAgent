"""TED Award (CAN) back-fill smoke test (dry-run, no DB writes by default).

Two phases (either skippable via flags):
  1) PEEK     one TedClient.search() call against the `can-*` query; dump
              top-level response keys + the first notice's keys/body. The
              `can-desg` notice type is the most likely first-call failure
              — see "What to do if it fails" in scripts/README.md.
  2) DRY-RUN  backfill_awards(dry_run=True) end-to-end; print the
              fetched/new/updated/companies_created/errors summary.

Run from anywhere; the script chdirs to backend/ so Settings loads .env.

Usage (from c:\\dev\\GTMAgent\\backend):
  .\\.venv\\Scripts\\python.exe .\\scripts\\awards_smoke.py
  .\\.venv\\Scripts\\python.exe .\\scripts\\awards_smoke.py --months 24 --limit 10
  .\\.venv\\Scripts\\python.exe .\\scripts\\awards_smoke.py --live --no-peek
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
from app.ingestion.awards_client import (  # noqa: E402
    AWARD_FIELDS,
    NOTICE_TYPES,
    _build_query,
    backfill_awards,
)
from app.ingestion.base_client import TedClient  # noqa: E402


def _peek(query: str, limit: int) -> None:
    print(f"\n--- PHASE 1: raw peek (limit={limit}) ---")
    print(f"QUERY: {query}")
    try:
        with TedClient() as client:
            page = client.search(query=query, fields=AWARD_FIELDS, page=1, limit=limit)
    except httpx.HTTPStatusError as e:
        print(f"\nHTTP {e.response.status_code} — FULL RESPONSE BODY:\n")
        print(e.response.text)
        body_lower = e.response.text.lower()
        if "can-desg" in body_lower or "can-social" in body_lower:
            print(
                "\nHINT: TED rejected one of the can-* notice-type values. "
                "Edit NOTICE_TYPES in backend/app/ingestion/awards_client.py — "
                "drop the unsupported value (likely `can-desg`, then `can-social` "
                "if still failing) and re-run."
            )
        raise

    print(f"RESPONSE TOP-LEVEL KEYS: {sorted(page.keys())}")
    print(f"totalNoticeCount: {page.get('totalNoticeCount')}")
    notices: list[dict] = []
    for key in ("notices", "results", "items", "data"):
        v = page.get(key)
        if isinstance(v, list):
            print(f"Found {len(v)} notices under key {key!r}")
            notices = v
            break
    if not notices:
        print("NO LIST FOUND under expected keys. Full response (truncated):")
        print(json.dumps(page, indent=2)[:2000])
        return

    # Per-notice summary — surfaces lot outcomes + which winner-* fields populated.
    winner_keys = (
        "winner-touchpoint-name",
        "winner-touchpoint-partname",
        "winner-identifier",
        "tendering-party-name",
        "organisation-name-tenderer",
        "BT-500-Business-European",
    )
    print("\n--- per-notice summary ---")
    print(f"{'#':>3}  {'pub-number':<14}  {'type':<14}  {'BT-142-LotResult':<40}  winner-fields-present")
    first_with_winner: dict | None = None
    for idx, notice in enumerate(notices, start=1):
        pub = str(notice.get("publication-number", "?"))[:14]
        ntype = str(notice.get("notice-type", "?"))[:14]
        bt142 = notice.get("BT-142-LotResult")
        bt142_str = json.dumps(bt142)[:40] if bt142 is not None else "—"
        wkeys_present = [k for k in winner_keys if notice.get(k) not in (None, [], {}, "")]
        wkeys_str = ",".join(wkeys_present) if wkeys_present else "—"
        print(f"{idx:>3}  {pub:<14}  {ntype:<14}  {bt142_str:<40}  {wkeys_str}")
        if first_with_winner is None and wkeys_present:
            first_with_winner = notice

    # Dump the first winner-bearing notice (if any) for field-shape inspection.
    if first_with_winner is not None:
        print("\n--- first notice with WINNER data populated ---")
        print(f"Keys: {sorted(first_with_winner.keys())}")
        print(f"JSON (truncated):\n{json.dumps(first_with_winner, indent=2)[:4000]}")
    else:
        print(
            "\nNo notice in this batch has any winner-* field populated. "
            "Either the entire batch is clos-nw (closed-no-winner), or our "
            "winner-field set is wrong. Re-run with a wider --limit or add a "
            "query filter to skip clos-nw notices."
        )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--cpv",
        help="Comma-separated CPVs (default: .env ALLOWED_CPV_CODES)",
    )
    p.add_argument(
        "--months",
        type=int,
        default=None,
        help="Back-fill window in months (default: settings.awards_backfill_months = 24)",
    )
    p.add_argument("--limit", type=int, default=5)
    p.add_argument("--no-peek", action="store_true", help="Skip phase 1")
    p.add_argument("--no-dry-run", action="store_true", help="Skip phase 2")
    p.add_argument(
        "--live",
        action="store_true",
        help="Flip phase 2 to dry_run=False — writes to awards + companies",
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
    months = args.months if args.months is not None else settings.awards_backfill_months

    print(f"Notice types: {NOTICE_TYPES}")
    print(f"CPV codes: {cpv}")
    print(f"Back-fill window: {months} months")

    if not args.no_peek:
        try:
            _peek(_build_query(cpv, months), args.limit)
        except Exception:
            logging.exception("Peek phase failed")
            return 1

    if not args.no_dry_run:
        mode = "LIVE (writes awards + companies)" if args.live else "dry-run"
        print(f"\n--- PHASE 2: {mode} back-fill (months={months}, limit={args.limit}) ---")
        summary = backfill_awards(
            cpv_codes=cpv,
            backfill_months=months,
            dry_run=not args.live,
            limit=args.limit,
            verbose=not args.quiet,
        )
        print(f"\nSUMMARY: {summary}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
