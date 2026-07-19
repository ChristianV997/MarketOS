"""backend.economics.supplier_feedback — observed supplier reliability loop.

``SupplierQuote.reliability`` (backend/validation/suppliers.py) is a static
per-class constant (or, in dry-run, a deterministic hash of the product
name) — it never updates from observed stockouts, delays, or quality
complaints, and supplier selection is effectively one-shot per product.

This module persists observed outcomes per (supplier, category) — reusing
the event-sourcing pattern already established in
``backend/orchestration/event_store.py`` — and derives a reliability
estimate that decays toward what's actually been observed via an
exponential moving average, rather than trusting the static class constant
forever. A supplier that starts stockout-prone gets down-ranked over time;
one that's been consistently reliable gets re-preferred.
"""
from __future__ import annotations

import os

# EMA weight on each new observation. Increased from 0.1 to 0.2 for faster
# convergence to observed reliability (quality shifts visible within 5-10 orders
# instead of 10-20). Still conservative enough that one bad outcome doesn't
# wildly swing an otherwise-solid track record.
DECAY_ALPHA = 0.2

# Prior reliability for a (supplier, category) pair with no observations
# yet — matches SupplierClient's rough base_reliability center (0.85-0.95
# across the four configured suppliers).
DEFAULT_PRIOR_RELIABILITY = 0.85


def supplier_feedback_live() -> bool:
    return os.getenv("SUPPLIER_FEEDBACK_LIVE", "false").lower() == "true"


class SupplierFeedbackStore:
    """Tracks observed reliability per (supplier, category), EMA-decayed."""

    def __init__(self):
        self._reliability: dict[tuple[str, str], float] = {}
        self._observation_counts: dict[tuple[str, str], int] = {}

    def record_outcome(self, supplier: str, category: str = "general",
                       stockout: bool = False, delayed: bool = False,
                       complaint: bool = False) -> float:
        """Record one observed order outcome; returns the updated EMA reliability.

        A "success" is an order with none of stockout/delayed/complaint;
        any one of them counts as a failure for that observation.
        """
        key = (supplier, category)
        prior = self._reliability.get(key, DEFAULT_PRIOR_RELIABILITY)
        success = 0.0 if (stockout or delayed or complaint) else 1.0
        updated = (1.0 - DECAY_ALPHA) * prior + DECAY_ALPHA * success

        self._reliability[key] = updated
        self._observation_counts[key] = self._observation_counts.get(key, 0) + 1

        try:
            from backend.orchestration.event_store import event_store, new_workflow_id
            event_store.append(
                new_workflow_id("supplierfb"), "supplier_feedback_recorded",
                workflow="supplier_feedback", step="record_outcome",
                data={
                    "supplier": supplier, "category": category,
                    "stockout": stockout, "delayed": delayed, "complaint": complaint,
                    "prior_reliability": round(prior, 4),
                    "updated_reliability": round(updated, 4),
                    "n_observations": self._observation_counts[key],
                },
            )
        except Exception:
            pass  # journaling must never break the feedback loop

        return updated

    def reliability_for(self, supplier: str, category: str = "general",
                        static_default: float | None = None) -> float:
        """Observed EMA reliability, or *static_default* if no observations
        exist yet for this (supplier, category) pair."""
        key = (supplier, category)
        if key not in self._reliability:
            return static_default if static_default is not None else DEFAULT_PRIOR_RELIABILITY
        return self._reliability[key]

    def observation_count(self, supplier: str, category: str = "general") -> int:
        return self._observation_counts.get((supplier, category), 0)

    def reset(self) -> None:
        """Test helper — clear all tracked observations."""
        self._reliability.clear()
        self._observation_counts.clear()


supplier_feedback = SupplierFeedbackStore()
