"""Identity and policy blockers for experiment drafts."""
from __future__ import annotations

from typing import Any, Mapping

from evaluation.commerce.experiment_draft_types import (
    APPROVAL_STATES, BUSINESS_MODELS, CHANNELS, HTML_MARK, MARKET_LANES, MEDICAL_CLAIM, text,
)


def collect_blockers(raw: Mapping[str, Any], ids: dict[str, str], registry: Mapping[str, str]) -> list[str]:
    out: list[str] = []
    if not ids["experiment_id"]:
        out.append("missing_experiment_id")
    if not ids["product_id"]:
        out.append("missing_product_id")
    if not ids["offer_id"]:
        out.append("missing_offer_id")
    if not ids["supplier"]:
        out.append("missing_supplier_offer")
    if ids["lane"] not in MARKET_LANES:
        out.append("missing_market_lane" if not ids["lane"] else "unsupported_market_lane")
    if not ids["workspace"]:
        out.append("missing_workspace")
    if ids["channel"] not in CHANNELS:
        out.append("unsupported_channel" if ids["channel"] else "missing_channel")
    if ids["model"] not in BUSINESS_MODELS:
        out.append("unsupported_business_model" if ids["model"] else "missing_business_model")
    if not ids["hypothesis"]:
        out.append("missing_hypothesis")
    if not ids["audience"]:
        out.append("missing_audience")
    if not ids["stop"]:
        out.append("missing_stop_condition")
    if not ids["budget"]:
        out.append("missing_budget_cap")
    if ids["approval_state"] not in APPROVAL_STATES:
        out.append("invalid_approval_state")
    if ids["referenced"] and ids["workspace"] and ids["referenced"] != ids["workspace"]:
        out.append("cross_workspace_reference")
    if raw.get("launch_authorized"):
        out.append("launch_authorized_input")
    creative = text(raw.get("creative_text") or ids["hypothesis"])
    if HTML_MARK.search(creative) or HTML_MARK.search(text(raw.get("landing_html"))):
        out.append("raw_html")
    if MEDICAL_CLAIM.search(creative):
        out.append("unsupported_medical_health_claim")
    if ids["experiment_id"] and ids["experiment_id"] in registry:
        out.append("duplicate_experiment_id")
    if ids["model"] == "affiliate" and ids["channel"] == "marketplace":
        out.append("affiliate_model_kept_separate_from_retail_channel")
    if raw.get("compliance_block") or ids["stop"].startswith("block_until"):
        out.append("compliance_or_support_evidence_incomplete")
    if raw.get("retailer_dominance") or raw.get("contribution_rejected"):
        out.append("retailer_dominance_contribution_rejected")
    if raw.get("insufficient_data"):
        out.append("insufficient_experiment_data")
    return out


def lifecycle_for(requested: str, approval: str, blockers: list[str]) -> str:
    if blockers:
        if "duplicate_experiment_id" in blockers or "retailer_dominance_contribution_rejected" in blockers:
            return "rejected"
        if "compliance_or_support_evidence_incomplete" in blockers or "insufficient_experiment_data" in blockers:
            return "evidence_incomplete"
        if any(item.startswith("missing_") or item.startswith("unsupported_") for item in blockers):
            return "evidence_incomplete"
        if "budget_exceeds_governor_cap" in blockers or "launch_authorized_input" in blockers:
            return "rejected"
        return "human_review"
    if approval == "approved_for_simulation":
        return "approved_for_simulation"
    if approval in {"not_requested", "pending"}:
        return "human_review"
    if approval == "rejected":
        return "rejected"
    return requested
