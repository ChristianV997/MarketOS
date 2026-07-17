"""core.portfolio — product-level budget fractions.

Historically this was a linear ROAS-share: score = max(roas, 0.1),
fraction = score / total. Two structural flaws: a product with one lucky
ROAS observation outranked one with 50 stable ones (no sample-size
awareness), and the module-global dict had no lock.

Now a thin wrapper over backend.decision.capital_policy: per-product ROAS
history (bounded deque) gives pred = mean and pred_width = std/√n — so
allocation weight reflects both performance *and* how much evidence backs
it. Products with <3 observations get the policy's wide default width
(0.5), matching how the LP always treated unknown uncertainty.

The public surface is unchanged: ``update_portfolio(pid, metrics)`` and
``allocate_budget(portfolio_data) -> {pid: fraction}`` (fractions sum to
1), so backend.decision.portfolio_engine's get_allocations()/top_products()
consumers keep working untouched. Shadow-mode gating lives in the policy
layer, not here — this function computes fractions, it doesn't spend.
"""
from __future__ import annotations

import threading
from collections import deque

import numpy as np

portfolio: dict = {}

_roas_history: dict[str, deque] = {}
_lock = threading.Lock()

_HISTORY_MAXLEN = 50
_MIN_SAMPLES_FOR_WIDTH = 3
_WIDE_DEFAULT_WIDTH = 0.5


def update_portfolio(product_id, metrics):
    with _lock:
        portfolio[product_id] = metrics
        roas = metrics.get("roas")
        if roas is None:
            revenue = metrics.get("revenue", 0)
            spend = metrics.get("spend", 0)
            roas = revenue / max(spend, 1)
        hist = _roas_history.setdefault(product_id, deque(maxlen=_HISTORY_MAXLEN))
        hist.append(float(roas))


def _pred_and_width(pid: str, m: dict) -> tuple[float, float]:
    """Mean ROAS + std/√n from history; wide width when evidence is thin."""
    with _lock:
        hist = list(_roas_history.get(pid, ()))
    if not hist:
        revenue = m.get("revenue", 0)
        spend = m.get("spend", 0)
        return max(revenue / max(spend, 1), 0.1), _WIDE_DEFAULT_WIDTH
    pred = max(float(np.mean(hist)), 0.1)
    if len(hist) < _MIN_SAMPLES_FOR_WIDTH:
        return pred, _WIDE_DEFAULT_WIDTH
    width = float(np.std(hist)) / np.sqrt(len(hist))
    return pred, max(width, 0.01)


def allocate_budget(portfolio_data):
    """{pid: fraction} — fractions sum to 1 (empty dict for no products)."""
    from backend.decision.capital_policy import allocate_capital

    pids = list(portfolio_data.keys())
    if not pids:
        return {}
    if len(pids) == 1:
        return {pids[0]: 1.0}

    arms = []
    for pid in pids:
        pred, width = _pred_and_width(pid, portfolio_data[pid])
        arms.append({"id": pid, "pred": pred, "pred_width": width,
                     "group": portfolio_data[pid].get("platform", "")})

    # Allocate against a unit budget → budgets are directly fractions.
    allocation = allocate_capital(arms, total_budget=1.0)
    total = sum(allocation.budgets) or 1.0
    return {pid: b / total for pid, b in zip(pids, allocation.budgets)}


def reset() -> None:
    """Test helper — clear portfolio and history."""
    with _lock:
        portfolio.clear()
        _roas_history.clear()
