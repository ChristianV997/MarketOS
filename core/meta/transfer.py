"""core.meta.transfer — initialize policies from similar cross-domain patterns."""
from __future__ import annotations

import math
from typing import Any

from core.meta.cross_domain_memory import CrossDomainMemory


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Return cosine similarity between two equal-length vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def find_similar(
    memory: CrossDomainMemory,
    query_embedding: list[float],
    top_k: int = 5,
    min_similarity: float = 0.7,
) -> list[dict[str, Any]]:
    """Find the *top_k* most similar entries in *memory* to *query_embedding*.

    Parameters
    ----------
    memory:
        :class:`CrossDomainMemory` to search.
    query_embedding:
        Query feature vector.
    top_k:
        Maximum number of results to return.
    min_similarity:
        Minimum cosine similarity threshold (entries below are excluded).

    Returns
    -------
    list[dict]
        Matching entries sorted by descending similarity, each enriched with
        a ``"similarity"`` key.
    """
    scored = []
    for entry in memory.get_all():
        sim = _cosine_similarity(query_embedding, entry["embedding"])
        if sim >= min_similarity:
            scored.append({**entry, "similarity": sim})
    scored.sort(key=lambda x: x["similarity"], reverse=True)
    return scored[:top_k]


def transfer_reward(
    memory: CrossDomainMemory,
    query_embedding: list[float],
    top_k: int = 5,
    min_similarity: float = 0.5,
) -> float:
    """Estimate a transfer reward by averaging rewards of similar past experiences.

    Returns 0.0 when no sufficiently similar entries exist.
    """
    similar = find_similar(memory, query_embedding, top_k, min_similarity)
    if not similar:
        return 0.0
    return sum(e["reward"] for e in similar) / len(similar)
