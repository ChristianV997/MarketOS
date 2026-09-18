"""Shared fixture seed for experiment-draft scenarios."""
from __future__ import annotations

from typing import Any


def planning(currency: str, contribution: str = "12.00") -> dict[str, Any]:
    return {
        "currency": currency,
        "break_even_cac": "18.00",
        "target_cac": "12.00",
        "break_even_roas": "2.5",
        "target_roas": "3.5",
        "contribution_before_cac": "22.00",
        "contribution_after_cac": contribution,
        "target_contribution": "15.00",
        "client_value_or_internal_profitability_effect": "planning_only",
        "evidence_state": "fixture",
        "assumed_at": "offline-deterministic",
        "assumptions": ("kernel_values_carried_not_recalculated",),
        "exchange_rate_metadata": {"policy": "no_silent_conversion"},
    }


def row(**kwargs: Any) -> dict[str, Any]:
    payload = {
        "workspace_id": "ws-alpha",
        "client_id": "client-alpha",
        "business_model": "retail_margin",
        "time_window": "14d",
        "success_metric": "planning_cpa_below_break_even",
        "guardrail_metrics": ("refund_rate",),
        "stop_condition": "stop_if_planning_cpa_above_break_even_cac",
        "approval_state": "approved_for_simulation",
        "budget_currency": "USD",
        "market_lane": "US-USD",
        "planning": planning("USD"),
    }
    payload.update(kwargs)
    return payload
