"""Validate and assemble an ExperimentDraft. Planning only."""
from __future__ import annotations

from typing import Any, Mapping

from evaluation.commerce.experiment_draft_blockers import collect_blockers, lifecycle_for
from evaluation.commerce.experiment_draft_economics import planning_from
from evaluation.commerce.experiment_draft_make import make_draft
from evaluation.commerce.experiment_draft_plan import fixture_promoted
from evaluation.commerce.experiment_draft_types import LANE_CURRENCY, LIVE_STATES, SCHEMA, STATES, ExperimentDraftError, replay_hash, secret, text

REGISTRY: dict[str, str] = {}


def reset_registry() -> None:
    REGISTRY.clear()


def _ids(raw: Mapping[str, Any]) -> dict[str, str]:
    return {
        "experiment_id": text(raw.get("experiment_id")),
        "product_id": text(raw.get("product_id")),
        "offer_id": text(raw.get("offer_id")),
        "supplier": text(raw.get("supplier_offer_id") or raw.get("supplier_offer_identity")),
        "lane": text(raw.get("market_lane")),
        "workspace": text(raw.get("workspace_id") or raw.get("workspace")),
        "client": text(raw.get("client_id") or raw.get("client")),
        "model": text(raw.get("business_model")),
        "channel": text(raw.get("channel")),
        "hypothesis": text(raw.get("hypothesis")),
        "audience": text(raw.get("target_audience") or raw.get("audience")),
        "stop": text(raw.get("stop_condition")),
        "budget": text(raw.get("budget_cap")),
        "approval_state": text(raw.get("approval_state") or "not_requested"),
        "approval_id": text(raw.get("approval_request_id")),
        "referenced": text(raw.get("referenced_workspace_id") or raw.get("workspace_id") or raw.get("workspace")),
    }


def build_experiment_draft(raw: Mapping[str, Any]):
    if not isinstance(raw, Mapping):
        raise ExperimentDraftError("malformed")
    if secret(raw):
        raise ExperimentDraftError("secret_shaped")
    requested = text(raw.get("lifecycle_state") or raw.get("state") or "proposed")
    if requested in LIVE_STATES:
        raise ExperimentDraftError("live_state_unavailable")
    if requested not in STATES:
        requested = "proposed"
    ids = _ids(raw)
    blockers = collect_blockers(raw, ids, REGISTRY)
    budget_currency = text(raw.get("budget_currency") or "").upper()
    expected = LANE_CURRENCY.get(ids["lane"])
    if budget_currency and expected and budget_currency != expected:
        blockers.append("mixed_currency")
    if not budget_currency:
        budget_currency = expected or "USD"
    planning = planning_from(raw.get("planning") if isinstance(raw.get("planning"), Mapping) else {}, ids["lane"] or "US-USD")
    if planning.currency != budget_currency:
        blockers.append("mixed_currency")
    if fixture_promoted(planning, raw):
        blockers.append("fixture_promoted_to_live")
    governor_cap = text(raw.get("governor_budget_cap")) or None
    if governor_cap and ids["budget"]:
        try:
            if float(ids["budget"]) > float(governor_cap):
                blockers.append("budget_exceeds_governor_cap")
        except ValueError:
            blockers.append("malformed_budget")
    lifecycle = lifecycle_for(requested, ids["approval_state"], blockers)
    next_action = "review_blockers" if blockers else "simulate_offline_then_human_review"
    if "missing_supplier_offer" in blockers:
        next_action = "collect_supplier_offer_identity"
    if "budget_exceeds_governor_cap" in blockers:
        next_action = "reduce_budget_to_governor_cap"
    if ids["approval_state"] == "not_requested" and not blockers:
        next_action = "file_approval_ledger_request_for_simulation"
    body = {
        "schema": SCHEMA, "experiment_id": ids["experiment_id"], "product_id": ids["product_id"],
        "offer_id": ids["offer_id"], "supplier_offer_id": ids["supplier"], "market_lane": ids["lane"],
        "workspace_id": ids["workspace"], "business_model": ids["model"], "channel": ids["channel"],
        "hypothesis": ids["hypothesis"], "budget_cap": ids["budget"], "budget_currency": budget_currency,
        "stop_condition": ids["stop"], "planning": planning.to_dict(), "approval_state": ids["approval_state"],
    }
    digest = replay_hash(body)
    draft = make_draft(raw=raw, ids=ids, budget_currency=budget_currency, governor_cap=governor_cap, planning=planning, lifecycle=lifecycle, next_action=next_action, digest=digest, blockers=blockers)
    if ids["experiment_id"] and "duplicate_experiment_id" not in blockers:
        REGISTRY[ids["experiment_id"]] = digest
    return draft
