"""backend.metrics.attribution — cross-platform revenue reconciliation.

The gap this closes: `campaign_metrics.jsonl` revenue is derived
per-campaign from *each ad platform's own self-reported ROAS*
(`orchestrator/main.py`: ``revenue_usd = est_spend * platform_roas``).
Meta and TikTok both use attribution windows generous enough (7-day
click, 1-day view, etc.) that the same real Shopify order can be claimed
by more than one platform's own reporting. Summing every platform's
self-reported revenue per product (as `profitability.py` used to) can
therefore credit a single sale more than once — inflating measured ROAS
and biasing every downstream allocation decision toward whichever
platform's attribution window is loosest.

This module does **not** invent an order-level join that doesn't exist:
Shopify orders in this codebase (`backend.integrations.shopify_client`)
carry no UTM/campaign tag today, so a true order_id → campaign_id
mapping isn't available. Instead it applies the standard closed-loop
attribution technique for exactly this situation — **revenue
reconciliation**: Shopify's own reported revenue for a window is ground
truth (it's the actual money that landed, full stop); if the platforms'
self-reported revenue for the same window sums to more than that ground
truth, every platform's credit is scaled down proportionally to its
reported share so the total can never exceed reality.

Both the raw (pre-reconciliation) and reconciled numbers are always
returned together — this is the shadow-mode comparison the rollout plan
requires, without needing a separate parallel code path.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger(__name__)


@dataclass
class ReconciliationResult:
    """Per-campaign_id reconciled revenue plus the aggregate comparison."""
    per_campaign_revenue: dict[str, float] = field(default_factory=dict)
    raw_total_revenue: float = 0.0
    reconciled_total_revenue: float = 0.0
    ground_truth_revenue: float | None = None
    scale_factor: float = 1.0
    applied: bool = False
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_total_revenue": round(self.raw_total_revenue, 2),
            "reconciled_total_revenue": round(self.reconciled_total_revenue, 2),
            "ground_truth_revenue": (
                round(self.ground_truth_revenue, 2)
                if self.ground_truth_revenue is not None else None),
            "scale_factor": round(self.scale_factor, 4),
            "applied": self.applied,
            "reason": self.reason,
            "overcounted_pct": (
                round((self.raw_total_revenue / self.reconciled_total_revenue - 1) * 100, 1)
                if self.reconciled_total_revenue > 0 else 0.0),
        }


def reconcile_revenue(
    campaign_revenue: dict[str, float],
    ground_truth_revenue: float | None,
) -> ReconciliationResult:
    """Scale platform-reported per-campaign revenue down to ground truth.

    ``campaign_revenue``: {campaign_id: revenue} as currently derived from
    each platform's own self-reported ROAS (never negative; callers should
    clip upstream).

    ``ground_truth_revenue``: the real, independently-observed revenue for
    the same product/window (Shopify order total) — the only number that
    isn't a platform's self-report. None/unavailable means we have no
    ground truth to reconcile against (e.g., dry-run with no Shopify data);
    in that case reconciliation is skipped and flagged, never guessed.

    Never scales *up* — if platforms under-report relative to ground
    truth (plausible: some organic/direct revenue isn't ad-attributed at
    all), that's not double-counting and isn't this function's problem to
    fix.
    """
    raw_total = sum(max(0.0, v) for v in campaign_revenue.values())

    if ground_truth_revenue is None:
        return ReconciliationResult(
            per_campaign_revenue=dict(campaign_revenue),
            raw_total_revenue=raw_total,
            reconciled_total_revenue=raw_total,
            ground_truth_revenue=None,
            scale_factor=1.0,
            applied=False,
            reason="no_ground_truth_available",
        )

    if raw_total <= ground_truth_revenue or raw_total <= 0:
        # Platforms didn't over-claim relative to ground truth — nothing to
        # scale down. (Under-claiming is a separate, non-double-counting
        # phenomenon and is left untouched.)
        return ReconciliationResult(
            per_campaign_revenue=dict(campaign_revenue),
            raw_total_revenue=raw_total,
            reconciled_total_revenue=raw_total,
            ground_truth_revenue=ground_truth_revenue,
            scale_factor=1.0,
            applied=False,
            reason="within_ground_truth",
        )

    scale = ground_truth_revenue / raw_total
    reconciled = {cid: max(0.0, rev) * scale for cid, rev in campaign_revenue.items()}
    _log.info("revenue_reconciled raw=%.2f ground_truth=%.2f scale=%.4f",
              raw_total, ground_truth_revenue, scale)
    return ReconciliationResult(
        per_campaign_revenue=reconciled,
        raw_total_revenue=raw_total,
        reconciled_total_revenue=sum(reconciled.values()),
        ground_truth_revenue=ground_truth_revenue,
        scale_factor=scale,
        applied=True,
        reason="scaled_to_ground_truth",
    )


__all__ = ["ReconciliationResult", "reconcile_revenue"]
