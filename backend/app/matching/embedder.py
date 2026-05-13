"""sentence-transformers ensemble embedding wrapper.

Loads three local models on CPU and exposes a unified `embed()` that
returns vectors from each. Downstream code can pick a single vector or
average across models for ensemble similarity.

Models used:
  - all-MiniLM-L6-v2          (fast, 384-d)
  - all-mpnet-base-v2         (accurate, 768-d)
  - multilingual-e5-large     (multilingual, 1024-d)
"""
from __future__ import annotations

from typing import Literal

ModelName = Literal[
    "all-MiniLM-L6-v2",
    "all-mpnet-base-v2",
    "multilingual-e5-large",
]


class EnsembleEmbedder:
    """Lazily loads the three sentence-transformers models on first use."""

    def __init__(self) -> None:
        self._models: dict[str, object] = {}

    # TODO: Phase 3 — lazy-load a SentenceTransformer and cache it
    def _get_model(self, name: ModelName) -> object:
        ...

    # TODO: Phase 3 — encode text and return a vector for the chosen model
    def embed(self, text: str, model: ModelName = "all-MiniLM-L6-v2") -> list[float]:
        ...

    # TODO: Phase 3 — encode with every model and return a dict[name, vector]
    def embed_all(self, text: str) -> dict[str, list[float]]:
        ...
