"""Downloads tender dossier PDFs and stores them on local/object storage.

Some dossiers sit behind a portal login and cannot be fetched anonymously;
those rows are flagged `is_restricted=True` for follow-up by the user.
"""
from __future__ import annotations

from pathlib import Path


class DossierDownloader:
    """Resolves dossier URLs from a tender notice and downloads them."""

    def __init__(self, storage_root: Path = Path("./storage/dossiers")) -> None:
        self.storage_root = storage_root

    # TODO: Phase 2 — download a single dossier PDF, returning (path, is_restricted)
    def download(self, tender_id: str, url: str) -> tuple[Path, bool]:
        ...
