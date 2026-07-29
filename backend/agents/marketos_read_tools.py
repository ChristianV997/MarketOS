"""Read-only, bounded MarketOS tools suitable for typed domain agents.

This is deliberately an adapter over the existing runtime skill registry, not
another tool registry.  It makes only attribution-safe semantic evidence
available to a model and never exposes launch, money, publishing, browser, or
account-changing operations.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence


_EVIDENCE_FIELDS = {
    "name", "product", "product_id", "title", "url", "source_ref",
    "description", "hook", "angle", "pattern", "campaign_id", "creative_id",
}


def _safe_evidence(payload: Any) -> dict[str, str | int | float | bool]:
    if not isinstance(payload, Mapping):
        return {}
    evidence: dict[str, str | int | float | bool] = {}
    for field in _EVIDENCE_FIELDS:
        value = payload.get(field)
        if isinstance(value, str):
            evidence[field] = value[:500]
        elif isinstance(value, (int, float, bool)):
            evidence[field] = value
    return evidence


class MarketOSReadTools:
    """Expose a minimal, read-only view of existing registered tools."""

    def __init__(self, registry: Any | None = None):
        self._registry = registry

    @property
    def registry(self) -> Any:
        if self._registry is None:
            from backend.runtime.skills.registry import get_skill_registry

            self._registry = get_skill_registry()
        return self._registry

    def semantic_evidence(self, query: str, top_k: int = 5) -> dict[str, list[dict[str, Any]]]:
        """Find bounded, read-only prior MarketOS evidence for a query."""
        normalized = str(query).strip()
        if not normalized:
            raise ValueError("query is required")
        bounded_top_k = max(1, min(int(top_k), 10))
        execution = self.registry.execute("semantic_search", {"query": normalized, "top_k": bounded_top_k})
        raw = execution.get("result", {}) if isinstance(execution, Mapping) else {}
        if not isinstance(raw, Mapping):
            return {}
        evidence: dict[str, list[dict[str, Any]]] = {}
        for collection, hits in raw.items():
            if not isinstance(hits, Sequence) or isinstance(hits, (str, bytes)):
                continue
            normalized_hits: list[dict[str, Any]] = []
            for hit in hits[:bounded_top_k]:
                if not isinstance(hit, Mapping):
                    continue
                normalized_hits.append({
                    "record_id": str(hit.get("record_id", ""))[:200],
                    "score": float(hit.get("score", 0.0)),
                    "evidence": _safe_evidence(hit.get("payload")),
                })
            evidence[str(collection)[:100]] = normalized_hits
        return evidence

    def functions(self) -> tuple[Callable[..., Any], ...]:
        return (self.semantic_evidence,)


def default_read_tools() -> tuple[Callable[..., Any], ...]:
    """Return the only tools domain agents may receive by default."""
    return MarketOSReadTools().functions()
