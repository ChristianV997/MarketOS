"""core.nlp.embeddings — sentence embedding via sentence-transformers (or fallback)."""
from __future__ import annotations

from typing import Any

_MODEL_NAME = "all-MiniLM-L6-v2"
_FALLBACK_EMBEDDING_DIM: int = 64
_model = None


def _get_model() -> Any:
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore[import]
            _model = SentenceTransformer(_MODEL_NAME)
        except Exception:
            _model = None
    return _model


def embed(texts: list[str]) -> list[list[float]]:
    """Return dense embeddings for *texts*.

    Uses ``sentence-transformers`` when available; falls back to a simple
    bag-of-character-ngram hash vector so the pipeline stays functional
    without the heavy ML dependency.

    Parameters
    ----------
    texts:
        List of strings to embed.

    Returns
    -------
    list[list[float]]
        One embedding vector per input string.
    """
    model = _get_model()
    if model is not None:
        try:
            result = model.encode(texts)
            return [list(map(float, v)) for v in result]
        except Exception:
            pass

    # Deterministic fallback: hash each text into a fixed-dim float vector
    def _hash_embed(text: str, dim: int = _FALLBACK_EMBEDDING_DIM) -> list[float]:
        vec = [0.0] * dim
        for i, ch in enumerate(text):
            vec[ord(ch) % dim] += 1.0 / (i + 1)
        return vec

    return [_hash_embed(t) for t in texts]
