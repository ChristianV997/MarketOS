"""Validate and assemble an ExperimentDraft. Planning only."""
from __future__ import annotations

from typing import Any, Mapping

from evaluation.commerce.experiment_draft_authorities import authority_bundle
from evaluation.commerce.experiment_draft_blockers import collect_blockers, lifecycle_for
from evaluation.commerce.experiment_draft_economics import planning_from
from evaluation.commerce.experiment_draft_models import ExperimentDraft
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
