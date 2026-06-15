"""CLI entry point for the ingestion layer.

Invoke from the `backend/` directory:

    python -m app.ingestion --mode both
    python -m app.ingestion --mode contracts --days 7 --dry-run
    python -m app.ingestion --mode awards --backfill-months 12 --limit 50
    python -m app.ingestion --mode both --no-dossiers

Exit code:
    0 — all configured jobs completed without errors or failed downloads.
    1 — at least one summary reported `errors > 0` or `failed > 0`. A
        non-zero `skipped_no_winner` is NOT an error (clos-nw notices
        are legitimate, just empty).
"""
from __future__ import annotations

import argparse
import logging
import sys
from typing import Sequence

from app.core.config import get_settings
from app.ingestion.awards_client import backfill_awards
from app.ingestion.dossier_downloader import download_dossiers
from app.ingestion.ted_client import poll_contract_notices


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m app.ingestion",
        description=(
            "Run the TED ingestion jobs (contracts, awards, dossiers) "
            "either in isolation or end-to-end."
        ),
    )
    p.add_argument(
        "--mode",
        choices=("contracts", "awards", "both"),
        default="both",
        help="Which ingestion jobs to run. Default: both.",
    )
    p.add_argument(
        "--cpv",
        action="append",
        default=None,
        help=(
            "CPV code to include. Pass multiple --cpv flags for several. "
            "Default: settings.cpv_code_list (from ALLOWED_CPV_CODES)."
        ),
    )
    p.add_argument(
        "--days",
        type=int,
        default=7,
        help="Contract-notice window in days (passed to poll_contract_notices).",
    )
    p.add_argument(
        "--backfill-months",
        dest="backfill_months",
        type=int,
        default=24,
        help="Award back-fill window in months (passed to backfill_awards).",
    )
    p.add_argument("--dry-run", action="store_true", help="Parse only; no DB writes.")
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap items processed per job (useful for smoke testing).",
    )
    p.add_argument(
        "--no-dossiers",
        action="store_true",
        help="Skip the dossier-download step at the end.",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Per-notice INFO logs.",
    )
    return p


def _configure_logging() -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the orchestrator. Returns the exit code (does NOT sys.exit)."""
    args = _build_parser().parse_args(argv)
    _configure_logging()

    settings = get_settings()
    cpv_codes = args.cpv if args.cpv else settings.cpv_code_list
    if not cpv_codes:
        print(
            "No CPV codes resolved. Set --cpv or ALLOWED_CPV_CODES in .env.",
            file=sys.stderr,
        )
        return 2

    results: dict[str, dict[str, int]] = {}

    if args.mode in ("contracts", "both"):
        results["contracts"] = poll_contract_notices(
            cpv_codes=cpv_codes,
            days=args.days,
            dry_run=args.dry_run,
            limit=args.limit,
            verbose=args.verbose,
        )

    if args.mode in ("awards", "both"):
        results["awards"] = backfill_awards(
            cpv_codes=cpv_codes,
            backfill_months=args.backfill_months,
            dry_run=args.dry_run,
            limit=args.limit,
            verbose=args.verbose,
        )

    if not args.no_dossiers:
        results["dossiers"] = download_dossiers(
            dry_run=args.dry_run,
            verbose=args.verbose,
            limit=args.limit,
        )

    print("\n=== Ingestion complete ===")
    for job, summary in results.items():
        print(f"  {job}: {summary}")

    any_errors = any(
        s.get("errors", 0) > 0 or s.get("failed", 0) > 0 for s in results.values()
    )
    return 1 if any_errors else 0


if __name__ == "__main__":
    sys.exit(main())
