"""sentence-transformers embedding wrapper.

Default model: `paraphrase-multilingual-MiniLM-L12-v2` (384-d) — matching
`company_profiles.embedding Vector(384)`. Multilingual on purpose: the TED
corpus (tender titles/descriptions, award histories) spans many EU languages,
and the English-only `all-MiniLM-L6-v2` under-scored non-English text. The
English model (also 384-d) is kept as a selectable alternative. The class keeps
the `EnsembleEmbedder` name and the `embed` / `embed_all` interface so it can
grow into the locked three-model ensemble (mpnet 768-d, e5 1024-d) later without
changing call sites.

The `SentenceTransformer` is **lazy-loaded on first use** (one-time model
download + ~10s load), so importing this module stays cheap and does not pull
torch at import time. Embeddings are L2-normalised, so a plain dot product
equals cosine similarity downstream.

NOTE: changing the default model invalidates any `company_profiles.embedding`
written by a different model — vectors from different models are NOT comparable,
so a tender embedded with the new model would score garbage against
old-model company vectors. Re-run `build_company_profiles` after switching.
"""
from __future__ import annotations

from typing import Literal

ModelName = Literal[
    "paraphrase-multilingual-MiniLM-L12-v2",
    "all-MiniLM-L6-v2",
    "all-mpnet-base-v2",
    "multilingual-e5-large",
]

DEFAULT_MODEL: ModelName = "paraphrase-multilingual-MiniLM-L12-v2"

_MODEL_DIMS: dict[str, int] = {
    "paraphrase-multilingual-MiniLM-L12-v2": 384,
    "all-MiniLM-L6-v2": 384,
    "all-mpnet-base-v2": 768,
    "multilingual-e5-large": 1024,
}

_ssl_injected = False


def _ensure_ssl_truststore() -> None:
    """Route HTTPS through the OS trust store (Windows AV/proxy SSL inspection
    otherwise breaks the one-time Hugging Face model download). Mirrors the
    truststore decision used by `TedClient`. Idempotent; best-effort."""
    global _ssl_injected
    if _ssl_injected:
        return
    try:
        import truststore

        truststore.inject_into_ssl()
    except Exception:  # truststore absent / already patched — fall back to default SSL
        pass
    _ssl_injected = True


class EnsembleEmbedder:
    """Lazily loads sentence-transformers model(s) on first use and caches them."""

    def __init__(self) -> None:
        self._models: dict[str, object] = {}

    def _get_model(self, name: ModelName) -> object:
        if name not in self._models:
            _ensure_ssl_truststore()
            # Imported here (not at module top) so importing this module stays
            # cheap and torch-free until an embedding is actually requested.
            from sentence_transformers import SentenceTransformer

            self._models[name] = SentenceTransformer(name)
        return self._models[name]

    def embed(self, text: str, model: ModelName = DEFAULT_MODEL) -> list[float]:
        """Encode `text` with `model`; returns an L2-normalised vector."""
        st_model = self._get_model(model)
        vector = st_model.encode(
            text or "",
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return [float(x) for x in vector]

    def embed_all(self, text: str) -> dict[str, list[float]]:
        """Encode with every loaded/available model.

        MVP returns only the default model; add ensemble members here to fan out.
        """
        return {DEFAULT_MODEL: self.embed(text, DEFAULT_MODEL)}

    @staticmethod
    def dim(model: ModelName = DEFAULT_MODEL) -> int:
        return _MODEL_DIMS[model]
