"""Construct ExperimentDraft after validation."""
from __future__ import annotations

from typing import Any, Mapping

from evaluation.commerce.experiment_draft_authorities import authority_bundle
from evaluation.commerce.experiment_draft_economics import PlanningEconomics
from evaluation.commerce.experiment_draft_models import ExperimentDraft
from evaluation.commerce.experiment_draft_types import SCHEMA, text


def make_draft(*, raw: Mapping[str, Any], ids: dict[str, str], budget_currency: str, governor_cap: str | None, planning: PlanningEconomics, lifecycle: str, next_action: str, digest: str, blockers: list[str]) -> ExperimentDraft:
    notes = ["planning_and_simulation_only", "governor_owns_caps", "approval_ledger_owns_approval"]
    if planning.evidence_state in {"fixture", "simulated", "assumed", "unknown"}:
        notes.append("fixture_cannot_attest_live")
    utm = raw.get("attribution_utm") if isinstance(raw.get("attribution_utm"), Mapping) else {}
    return ExperimentDraft(
        schema=SCHEMA,
        experiment_id=ids["experiment_id"] or "unavailable",
        product_id=ids["product_id"],
        offer_id=ids["offer_id"],
        supplier_offer_id=ids["supplier"],
        market_lane=ids["lane"],
        workspace_id=ids["workspace"],
        client_id=ids["client"],
        business_model=ids["model"],
        channel=ids["channel"],
        hypothesis=ids["hypothesis"],
        target_audience=ids["audience"],
        creative_brief=text(raw.get("creative_brief") or ids["hypothesis"]),
        creative_draft_ids=tuple(text(item) for item in (raw.get("creative_draft_ids") or ()) if text(item)),
        landing_page_draft_id=text(raw.get("landing_page_draft_id") or raw.get("site_draft_id")),
        budget_cap=ids["budget"],
        budget_currency=budget_currency,
        governor_budget_cap=governor_cap,
        time_window=text(raw.get("time_window") or "14d"),
        success_metric=text(raw.get("success_metric") or "planning_cpa_below_break_even"),
        guardrail_metrics=tuple(text(item) for item in (raw.get("guardrail_metrics") or ("support_ticket_rate", "refund_rate")) if text(item)),
        stop_condition=ids["stop"],
        attribution_utm={
            "utm_source": text(utm.get("utm_source")) or "marketos-draft",
            "utm_medium": text(utm.get("utm_medium")) or ids["channel"] or "draft",
            "utm_campaign": ids["experiment_id"] or "draft",
        },
        evidence_refs=tuple(text(item) for item in (raw.get("evidence_refs") or ()) if text(item)),
        evidence_state=planning.evidence_state,
        assumptions=planning.assumptions or ("planning_values_are_not_observed_performance",),
        confidence=text(raw.get("confidence") or "planning_only"),
        approval_state=ids["approval_state"],
        approval_request_id=ids["approval_id"],
        lifecycle_state=lifecycle,
        planning=planning,
        next_human_action=next_action,
        replay_hash=digest,
        live_action_allowed=False,
        notes=tuple(notes),
        blocked_reasons=tuple(blockers),
        authorities=authority_bundle(raw),
    )
