"""Import smoke test — every stub module must be importable."""
from __future__ import annotations

import importlib

import pytest

MODULES = [
    "app.main",
    "app.core.config",
    "app.core.logging",
    "app.api.deps",
    "app.api.v1.tenders",
    "app.api.v1.awards",
    "app.api.v1.companies",
    "app.api.v1.matches",
    "app.api.v1.emails",
    "app.api.v1.feedback",
    "app.ingestion.ted_client",
    "app.ingestion.awards_client",
    "app.ingestion.dossier_downloader",
    "app.ingestion.scheduler",
    "app.understanding.extractor",
    "app.understanding.schemas",
    "app.understanding.validator",
    "app.matching.disqualifier",
    "app.matching.embedder",
    "app.matching.semantic",
    "app.matching.rules",
    "app.matching.lr_weights",
    "app.matching.pipeline",
    "app.generation.evidence",
    "app.generation.drafter",
    "app.generation.validator",
    "app.agent.controller",
    "app.db.session",
    "app.db.models",
]


@pytest.mark.parametrize("module_path", MODULES)
def test_module_imports(module_path: str) -> None:
    importlib.import_module(module_path)
