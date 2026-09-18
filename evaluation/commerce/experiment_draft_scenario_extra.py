"""Remaining fixture scenarios plus runner."""
from __future__ import annotations

from typing import Any

from evaluation.commerce.experiment_draft import build_experiment_draft, simulate_experiment_draft
from evaluation.commerce.experiment_draft_scenario_seed import planning, row

EXTRA = {
    "affiliate_referral_separate": row(
        experiment_id="exp-aff-006", product_id="prod-desk-org", offer_id="offer-affiliate-desk",
        supplier_offer_id="partner-desk-aff", business_model="affiliate", channel="affiliate",
        hypothesis="Affiliate payout planning stays off the retail-margin waterfall.",
        target_audience="US desk-organization affiliates", creative_draft_ids=("creative-aff-06",),
        landing_page_draft_id="site-aff-06", budget_cap="25", governor_budget_cap="100",
        success_metric="affiliate_epc_planning", guardrail_metrics=("disclosure_present",),
        stop_condition="stop_if_disclosure_missing", approval_request_id="apr-aff-006",
        planning=planning("USD", "4.00"),
    ),
    "marketplace_fees_returns": row(
        experiment_id="exp-mkt-007", product_id="prod-organizer", offer_id="offer-amazon-organizer",
        supplier_offer_id="cj-organizer", channel="marketplace",
        hypothesis="Marketplace fee and return assumptions must stay explicit.",
        target_audience="Amazon US home-office buyers", creative_draft_ids=("creative-mkt-07",),
        landing_page_draft_id="site-mkt-07", budget_cap="60", governor_budget_cap="200",
        success_metric="contribution_after_fees_and_returns",
        guardrail_metrics=("return_rate", "marketplace_fee_rate"),
        stop_condition="stop_if_return_rate_above_12pct", approval_request_id="apr-mkt-007",
        planning=planning("USD", "6.50"),
    ),
    "mxn_lane": row(
        experiment_id="exp-mx-008", product_id="prod-organizer-mx", offer_id="offer-mx-organizer",
        supplier_offer_id="cj-organizer-mx", market_lane="MX-MXN", workspace_id="ws-mx", client_id="client-mx",
        channel="paid_social", hypothesis="MXN lane stays isolated from USD planning values.",
        target_audience="MX home-office buyers", creative_draft_ids=("creative-mx-08",),
        landing_page_draft_id="site-mx-08", budget_cap="2500", budget_currency="MXN", governor_budget_cap="8000",
        approval_request_id="apr-mx-008", planning=planning("MXN", "180.00"),
    ),
    "usd_lane": row(
        experiment_id="exp-us-009", product_id="prod-organizer-us", offer_id="offer-us-organizer",
        supplier_offer_id="cj-organizer-us", workspace_id="ws-us", client_id="client-us",
        channel="paid_social", hypothesis="USD lane stays isolated from MXN planning values.",
        target_audience="US home-office buyers", creative_draft_ids=("creative-us-09",),
        landing_page_draft_id="site-us-09", budget_cap="120", governor_budget_cap="400",
        approval_request_id="apr-us-009", planning=planning("USD", "11.00"),
    ),
}


def merge_payloads(core: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    data = dict(core)
    data.update(EXTRA)
    return data


def run_records(payloads: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for name, payload in payloads.items():
        draft = build_experiment_draft(payload)
        sim = simulate_experiment_draft(draft)
        records.append({
            "scenario": name,
            "lifecycle_state": draft.lifecycle_state,
            "blocked_reasons": list(draft.blocked_reasons),
            "simulation": sim.classification,
            "live_action_allowed": False,
            "currency": draft.planning.currency,
            "replay_hash": draft.replay_hash,
            "governor_status": draft.authorities.get("governor", {}).get("status"),
            "ledger_status": draft.authorities.get("approval_ledger", {}).get("status"),
        })
    return records
