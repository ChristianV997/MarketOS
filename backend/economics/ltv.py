"""backend.economics.ltv — minimal CAC-vs-LTV repeat-purchase tracker.

Before this module, every margin/profitability calculation in the codebase
was single-order economics: a consumable with strong repeat-purchase
potential scored identically to a one-off novelty item with the same
first-order margin. No remarketing infrastructure exists yet, so this
starts with the simplest useful signal — did a given customer order again
within a bounded window? — rather than building a full CRM/attribution
stack.

Repeat rate is estimated per product category via a Beta-Binomial
hierarchical model: a category-benchmark prior, updated by observed repeat
orders as evidence accumulates. Early on (few observations) the prior
dominates; as evidence accumulates, the observed rate takes over. This is
the standard shrinkage-toward-prior behavior of a Beta-Binomial posterior
mean and needs no additional machinery to get right.

``effective_cac`` folds the estimated repeat rate into a single number:
CAC is sunk cost on order 1, but a product with a real repeat rate earns
that CAC back (partially) on subsequent orders at near-zero incremental
acquisition cost — so its *effective* CAC per lifetime dollar of margin is
lower than its first-order CAC, exactly the correction
``backend/validation/margin_calculator.py::calculate_ltv_adjusted_margin``
needs to stop under-valuing consumables relative to one-off novelty items.

Optional PyMC-Marketing extra (see requirements-optional.txt):
pymc_marketing_available() gates a future BG/NBD + Gamma-Gamma CLV path —
a fuller model than this module's Beta-Binomial repeat-rate estimate, but
one that needs real per-customer frequency/recency/monetary transaction
history (this module currently only tracks last-order-timestamp per
customer per category) and enough order volume per category
(PYMC_CLV_MIN_ORDERS, default 1000) to fit meaningfully. Installing the
package is necessary but not sufficient to activate it — until that
transaction-history plumbing exists, the Beta-Binomial estimate below
remains what's actually used regardless of order volume or whether
pymc-marketing is installed.
"""
from __future__ import annotations

import os
import time

# Beta-Binomial prior: category benchmark repeat rate (order again within
# REPEAT_WINDOW_DAYS). "general" is a conservative middle estimate for an
# unclassified product.
CATEGORY_REPEAT_RATE_PRIOR = {
    "general":     0.10,
    "consumables": 0.40,
    "beauty":      0.30,
    "apparel":     0.15,
    "electronics": 0.08,
    "jewelry":     0.05,
    "home":        0.12,
}

# Pseudo-observation strength behind the prior — how many real observations
# it takes before observed data outweighs the category benchmark. 20 is a
# deliberately conservative floor: a handful of early repeat/non-repeat
# orders shouldn't swing the estimate wildly.
PRIOR_STRENGTH = 20

# Window within which a second order from the same customer counts as a
# "repeat" for this simple tracker (vs. an unrelated later acquisition).
REPEAT_WINDOW_DAYS = 60
REPEAT_WINDOW_SECONDS = REPEAT_WINDOW_DAYS * 86_400

# PyMC-Marketing optional extra — see requirements-optional.txt and the
# module docstring for exactly what's gated here and why it's not active
# yet regardless of order volume.
PYMC_CLV_MIN_ORDERS = int(os.getenv("PYMC_CLV_MIN_ORDERS", "1000"))


def pymc_marketing_available() -> bool:
    try:
        import pymc_marketing  # noqa: F401
        return True
    except ImportError:
        return False


# Repeat orders carry ~zero incremental CAC but aren't free to fulfill
# (shipping, payment fees, some return risk) — this fraction discounts a
# repeat order's margin contribution relative to a full first-order margin
# when computing effective CAC.
AVG_REPEAT_MARGIN_FRAC = 0.6


def category_repeat_rate_prior(category: str = "general") -> float:
    """Beta-Binomial prior repeat rate for *category*.

    Consults backend.data.category_priors (Phase I) for an Olist-derived
    repeat_rate first — a no-op today (returns *legacy* unchanged) until
    both CATEGORY_PRIORS_LIVE is set and scripts/ingest_category_priors.py
    has actually populated real data for *category*.
    """
    legacy = CATEGORY_REPEAT_RATE_PRIOR.get(category, CATEGORY_REPEAT_RATE_PRIOR["general"])
    try:
        from backend.data.category_priors import category_prior
        return category_prior(category, "repeat_rate", legacy)
    except Exception:
        return legacy


class CohortTracker:
    """Per-customer order history and per-category repeat-rate posterior.

    Bounded by design: this is a "minimal viable" tracker (per the Phase 6
    plan), not a full CRM. Order history is retained only long enough to
    detect a repeat within ``REPEAT_WINDOW_DAYS`` and is not otherwise
    persisted across process restarts in this phase — acceptable for
    surfacing the repeat-purchase signal into scoring, revisit if durable
    cross-restart cohort history becomes a priority.
    """

    def __init__(self):
        # customer_id -> {category: last_order_ts}
        self._last_order: dict[str, dict[str, float]] = {}
        # category -> observed repeat count / total orders eligible to repeat
        self._repeat_counts: dict[str, int] = {}
        self._total_counts: dict[str, int] = {}
        # order ids already recorded — lets callers safely retry
        # record_order() for the same order (e.g. a crash-recovery retry in
        # backend.commerce.orders._run_side_effects) without double-counting.
        self._recorded_order_ids: set[str] = set()

    def record_order(self, customer_id: str, category: str, ts: float | None = None,
                     order_id: str = "") -> bool:
        """Record one order; returns True if it was detected as a repeat.

        A missing/empty ``customer_id`` cannot be linked across orders (no
        remarketing/customer-identity infra exists yet) — it's recorded as
        a first-order-only observation and never counts toward
        ``_repeat_counts``, matching the honest "no signal" default used
        throughout this codebase's other adaptive modules.

        Pass ``order_id`` when the same logical order could plausibly be
        recorded more than once (webhook retry after a partial crash) — a
        repeat order_id is a no-op instead of double-counting.
        """
        if order_id:
            if order_id in self._recorded_order_ids:
                return False
            self._recorded_order_ids.add(order_id)

        ts = time.time() if ts is None else ts
        self._total_counts[category] = self._total_counts.get(category, 0) + 1

        is_repeat = False
        if customer_id:
            history = self._last_order.setdefault(customer_id, {})
            last_ts = history.get(category)
            if last_ts is not None and (ts - last_ts) <= REPEAT_WINDOW_SECONDS:
                is_repeat = True
                self._repeat_counts[category] = self._repeat_counts.get(category, 0) + 1
            history[category] = ts

        return is_repeat

    def repeat_rate(self, category: str = "general") -> float:
        """Beta-Binomial posterior mean repeat rate for *category*.

        posterior_mean = (prior_strength * prior + observed_repeats)
                        / (prior_strength + observed_total)

        This is the estimate actually used today regardless of order
        volume or whether pymc-marketing is installed — see
        pymc_marketing_available()/PYMC_CLV_MIN_ORDERS and the module
        docstring for what a future BG/NBD+Gamma-Gamma path still needs
        (real per-customer transaction history this tracker doesn't keep).
        """
        prior = category_repeat_rate_prior(category)
        repeats = self._repeat_counts.get(category, 0)
        total = self._total_counts.get(category, 0)
        return (PRIOR_STRENGTH * prior + repeats) / (PRIOR_STRENGTH + total)

    def observation_count(self, category: str = "general") -> int:
        return self._total_counts.get(category, 0)

    def reset(self) -> None:
        """Test helper — clear all tracked history."""
        self._last_order.clear()
        self._repeat_counts.clear()
        self._total_counts.clear()


cohort_tracker = CohortTracker()


def effective_cac(first_order_cac: float, category: str = "general",
                   avg_repeat_margin_frac: float = AVG_REPEAT_MARGIN_FRAC,
                   tracker: CohortTracker | None = None) -> float:
    """CAC amortized against expected lifetime value, not just order 1.

    effective_cac = first_order_cac / (1 + repeat_rate * avg_repeat_margin_frac)

    A product with a 40% repeat rate (consumables) earns back a real
    fraction of its acquisition cost on the second (and further) order at
    near-zero incremental spend; a 5% repeat rate (jewelry, one-offs)
    barely moves the number. Never returns a value larger than
    ``first_order_cac`` (the denominator is always >= 1).
    """
    tracker = tracker or cohort_tracker
    r = tracker.repeat_rate(category)
    return first_order_cac / (1.0 + r * avg_repeat_margin_frac)
