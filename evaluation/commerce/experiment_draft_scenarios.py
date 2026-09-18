"""Fixture-only experiment draft scenarios. Planning records, not campaigns."""
from __future__ import annotations

from typing import Any

from evaluation.commerce.experiment_draft import build_experiment_draft, simulate_experiment_draft
from evaluation.commerce.experiment_draft_scenario_seed import planning, row


def scenario_payloads() -> dict[str, dict[str, Any]]:
    return {
        "hydroponics_content_paid_social": row(
            experiment_id="exp-hydro-001", product_id="prod-hydro-tower", offer_id="offer-hydro-starter",
            supplier_offer_id="cj-hydro-sku-1", channel="paid_social",
            hypothesis="Short hydroponics how-to clips will lower planning CPA versus static catalog ads.",
            target_audience="US apartment gardeners 25-44", creative_draft_ids=("creative-hydro-01",),
            landing_page_draft_id="site-hydro-01", budget_cap="150", governor_budget_cap="400",
            guardrail_metrics=("refund_rate", "comment_toxicity"),
            stop_condition="stop_if_planning_cpa_above_break_even_cac_for_3_days", approval_request_id="apr-hydro-001",
        ),
        "smart_pet_support_risk": row(
            experiment_id="exp-pet-002", product_id="prod-smart-feeder", offer_id="offer-feeder",
            supplier_offer_id="spocket-feeder-9", channel="content",
            hypothesis="Support-first creative reduces return risk on connected pet hardware.",
            target_audience="US pet households", creative_draft_ids=("creative-pet-02",),
            landing_page_draft_id="site-pet-02", budget_cap="80", governor_budget_cap="200",
            success_metric="support_ticket_rate_below_8pct",
            guardrail_metrics=("support_ticket_rate", "refund_rate", "app_review_score"),
            stop_condition="pause_if_support_ticket_rate_above_8pct", approval_request_id="apr-pet-002",
            planning=planning("USD", "8.00"),
        ),
        "solar_4g_compliance_block": row(
            experiment_id="exp-solar-003", product_id="prod-solar-4g", offer_id="offer-solar-kit",
            supplier_offer_id="ali-solar-4g", market_lane="MX-MXN", workspace_id="ws-beta", client_id="client-beta",
            channel="marketplace", hypothesis="Solar 4G kits cannot be promoted until SIM and support evidence exist.",
            target_audience="MX rural connectivity buyers", creative_draft_ids=("creative-solar-03",),
            landing_page_draft_id="site-solar-03", budget_cap="2000", budget_currency="MXN", governor_budget_cap="5000",
            time_window="21d", success_metric="compliance_evidence_complete",
            guardrail_metrics=("sim_registration_gap", "support_coverage"),
            stop_condition="block_until_sim_and_support_evidence", approval_state="blocked", approval_request_id="",
            planning=planning("MXN", "90.00"), lifecycle_state="evidence_incomplete", compliance_block=True,
        ),
        "commodity_electronics_rejected": row(
            experiment_id="exp-elec-004", product_id="prod-usb-hub", offer_id="offer-usb-hub",
            supplier_offer_id="cj-usb-hub", channel="marketplace",
            hypothesis="Commodity USB hubs lose to retailer dominance on contribution.",
            target_audience="US commodity electronics shoppers", creative_draft_ids=("creative-elec-04",),
            landing_page_draft_id="site-elec-04", budget_cap="50", governor_budget_cap="50", time_window="7d",
            success_metric="contribution_after_cac", guardrail_metrics=("retailer_price_gap",),
            stop_condition="reject_if_contribution_after_cac_not_positive", approval_state="rejected",
            approval_request_id="apr-elec-004", planning=planning("USD", "0.40"),
            retailer_dominance=True, contribution_rejected=True,
        ),
        "service_client_cro_insufficient": row(
            experiment_id="exp-cro-005", product_id="svc-audit", offer_id="offer-audit",
            supplier_offer_id="internal-service-audit", workspace_id="ws-gamma", client_id="client-gamma",
            business_model="service", channel="cro",
            hypothesis="Service landing-page CRO needs more session evidence before a test design.",
            target_audience="existing service clients", creative_draft_ids=(), landing_page_draft_id="site-cro-05",
            budget_cap="0", governor_budget_cap="100", success_metric="qualified_session_sample",
            guardrail_metrics=("sample_size",), stop_condition="hold_until_sample_size_20",
            approval_state="pending", approval_request_id="apr-cro-005", planning=planning("USD", "40.00"),
            insufficient_data=True,
        ),
    }
