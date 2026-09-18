"""Frozen experiment draft and simulation records."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from evaluation.commerce.experiment_draft_authorities import GOVERNOR_ACTION, LEDGER_REQUEST_TYPE
from evaluation.commerce.experiment_draft_economics import PlanningEconomics


@dataclass(frozen=True)
class ExperimentDraft:
    schema: str
    experiment_id: str
    product_id: str
    offer_id: str
    supplier_offer_id: str
    market_lane: str
    workspace_id: str
    client_id: str
    business_model: str
    channel: str
    hypothesis: str
    target_audience: str
    creative_brief: str
    creative_draft_ids: tuple[str, ...]
    landing_page_draft_id: str
    budget_cap: str
    budget_currency: str
    governor_budget_cap: str | None
    time_window: str
    success_metric: str
    guardrail_metrics: tuple[str, ...]
    stop_condition: str
    attribution_utm: Mapping[str, str]
    evidence_refs: tuple[str, ...]
    evidence_state: str
    assumptions: tuple[str, ...]
    confidence: str
    approval_state: str
    approval_request_id: str
    lifecycle_state: str
    planning: PlanningEconomics
    next_human_action: str
    replay_hash: str
    live_action_allowed: bool = False
    notes: tuple[str, ...] = ()
    blocked_reasons: tuple[str, ...] = ()
    authorities: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "experiment_id": self.experiment_id,
            "product_id": self.product_id,
            "offer_id": self.offer_id,
            "supplier_offer_id": self.supplier_offer_id,
            "market_lane": self.market_lane,
            "workspace_id": self.workspace_id,
            "client_id": self.client_id,
            "business_model": self.business_model,
            "channel": self.channel,
            "hypothesis": self.hypothesis,
            "target_audience": self.target_audience,
            "creative_brief": self.creative_brief,
            "creative_draft_ids": list(self.creative_draft_ids),
            "landing_page_draft_id": self.landing_page_draft_id,
            "budget_cap": self.budget_cap,
            "budget_currency": self.budget_currency,
            "governor_budget_cap": self.governor_budget_cap,
            "governor_action_referenced": GOVERNOR_ACTION,
            "time_window": self.time_window,
            "success_metric": self.success_metric,
            "guardrail_metrics": list(self.guardrail_metrics),
            "stop_condition": self.stop_condition,
            "attribution_utm": dict(self.attribution_utm),
            "evidence_refs": list(self.evidence_refs),
            "evidence_state": self.evidence_state,
            "assumptions": list(self.assumptions),
            "confidence": self.confidence,
            "approval_state": self.approval_state,
            "approval_request_id": self.approval_request_id,
            "approval_ledger_request_type": LEDGER_REQUEST_TYPE,
            "lifecycle_state": self.lifecycle_state,
            "planning": self.planning.to_dict(),
            "next_human_action": self.next_human_action,
            "replay_hash": self.replay_hash,
            "live_action_allowed": False,
            "notes": list(self.notes),
            "blocked_reasons": list(self.blocked_reasons),
            "authorities": dict(self.authorities),
        }
