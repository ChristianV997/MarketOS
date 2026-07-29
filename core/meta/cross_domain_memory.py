"""core.meta.cross_domain_memory — store (domain, embedding, reward) tuples."""
from __future__ import annotations

from collections import deque
from typing import Any


class CrossDomainMemory:
    """In-memory store for cross-domain experience tuples.

    Each entry is ``{"domain": str, "embedding": list[float], "reward": float}``.
    """

    def __init__(self, maxlen: int = 5000) -> None:
        self._store: deque[dict[str, Any]] = deque(maxlen=maxlen)

    def store(self, domain: str, embedding: list[float], reward: float) -> None:
        """Append a new experience tuple."""
        self._store.append({"domain": domain, "embedding": embedding, "reward": reward})

    def get_all(self) -> list[dict[str, Any]]:
        """Return all stored tuples as a list."""
        return list(self._store)

    def by_domain(self, domain: str) -> list[dict[str, Any]]:
        """Return tuples filtered to *domain*."""
        return [e for e in self._store if e["domain"] == domain]

    def __len__(self) -> int:
        return len(self._store)
