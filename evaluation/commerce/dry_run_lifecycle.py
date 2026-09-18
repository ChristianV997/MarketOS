"""Deterministic dry-run commerce lifecycle.

Implements the 15-stage lifecycle the integration spec requires:

    evidence -> supplier_offer -> market_lane -> unit_economics ->
    competition -> promotion_gate -> offer -> experiment_draft ->
    campaign_draft -> simulated_order -> supplier_dispatch_draft ->
    tracking_draft -> delivery -> return_rma -> contribution_reconciliation

Every step is simulated or draft-only: this module never calls a provider,
places an order, spends on ads, or mutates an external system — it composes
the financial kernel (``backend.economics.kernel``), the canonical commerce
concepts (``evaluation.commerce.canonical``), and the promotion gate state
machine (``evaluation.commerce.promotion``) without re-deriving any of their
math or state rules.

An offer only reaches the "offer" step and beyond once the promotion gate
allows at least ``launch_draft``; the experiment/campaign/order/fulfillment
steps additionally require ``experiment_ready``. A blocked candidate still
gets a full 15-row report — the downstream rows are explicit
``blocked_upstream`` entries carrying the same blockers the promotion
decision recorded, so the report is a complete, honest trace rather than a
truncated one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from backend.economics.kernel import MarketLane, Money, UnitEconomicsAssumptions, UnitEconomicsResult

from .business_model_economics import calculate_offer_economics
from .canonical import BusinessModel, CommercialOwnership, CompetitionSnapshot, SupplierOfferIdentity
from .promotion import STAGES, PromotionDecision, evaluate_promotion

LIFECYCLE_STEPS: tuple[str, ...] = (
    "evidence",
    "supplier_offer",
    "market_lane",
    "unit_economics",
    "competition",
    "promotion_gate",
    "offer",
    "experiment_draft",
    "campaign_draft",
    "simulated_order",
    "supplier_dispatch_draft",
    "tracking_draft",
    "delivery",
    "return_rma",
    "contribution_reconciliation",
)

# Steps from "offer" onward require the promotion decision to have reached
# at least "launch_draft"; steps from "experiment_draft" onward additionally
# require "experiment_ready".
_OFFER_STEP_INDEX = LIFECYCLE_STEPS.index("offer")
_EXPERIMENT_STEP_INDEX = LIFECYCLE_STEPS.index("experiment_draft")


@dataclass(frozen=True)
class DryRunScenarioInput:
    scenario_id: str
    candidate_id: str
    business_model: BusinessModel
    price: Money
    product_cost: Money | None
    lane: MarketLane
    assumptions: UnitEconomicsAssumptions
    ownership: CommercialOwnership
    competition: CompetitionSnapshot
    gate_satisfaction: Mapping[str, bool]
    evidence_state: str
    workspace_id: str = "dry-run"
    supplier_offer: SupplierOfferIdentity | None = None
    customer_facing_promise: str = ""


@dataclass(frozen=True)
class DryRunStepResult:
    step: str
    status: str  # "simulated" | "draft" | "blocked_upstream"
    detail: Mapping[str, Any]
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"step": self.step, "status": self.status, "detail": dict(self.detail), "reasons": list(self.reasons)}


@dataclass(frozen=True)
class DryRunLifecycleReport:
    scenario_id: str
    candidate_id: str
    achievable_stage: str
    promoted_to_launch: bool
    steps: tuple[DryRunStepResult, ...]
    economics: UnitEconomicsResult
    promotion: PromotionDecision
    dry_run: bool = True
    live_actions_taken: bool = False
    commerce_packet: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "candidate_id": self.candidate_id,
            "achievable_stage": self.achievable_stage,
            "promoted_to_launch": self.promoted_to_launch,
            "steps": [step.to_dict() for step in self.steps],
            "economics": self.economics.to_dict(),
            "promotion": self.promotion.to_dict(),
            "dry_run": self.dry_run,
            "live_actions_taken": self.live_actions_taken,
            "commerce_packet": dict(self.commerce_packet),
        }


def _assumptions_payload(assumptions: UnitEconomicsAssumptions) -> dict[str, Any]:
    """Serialize assumptions without adding a second kernel schema."""
    payload: dict[str, Any] = {}
    for name in (
        "supplier_shipping", "domestic_shipping", "international_shipping", "brokerage_fee",
        "payment_fee_fixed", "platform_fee_fixed", "ad_spend", "cac",
        "payment_fee_rate", "platform_fee_rate", "marketplace_fee_rate", "affiliate_fee_rate",
        "tax_rate", "duty_rate", "return_rate", "defect_rate", "warranty_rate",
        "support_reserve_rate", "chargeback_rate", "fx_reserve_rate", "discount_rate",
        "conversion_rate", "refund_lag_days", "target_margin_rate",
    ):
        value = getattr(assumptions, name)
        if isinstance(value, Money):
            payload[name] = value.to_dict()
        elif value is not None:
            payload[name] = str(value)
    payload["evidence_refs"] = [item.to_dict() for item in assumptions.evidence_refs]
    return payload


def run_dry_run_lifecycle(scenario: DryRunScenarioInput) -> DryRunLifecycleReport:
    """Run one candidate through the 15-stage dry-run lifecycle.

    ``product_cost`` may be ``None`` for non-retail_margin business models
    (see ``business_model_economics.calculate_offer_economics``); a
    commission/affiliate/lead_generation scenario must instead put its
    revenue basis directly on ``scenario.price``.
    """
    economics = calculate_offer_economics(
        scenario.business_model,
        price=scenario.price,
        product_cost=scenario.product_cost,
        lane=scenario.lane,
        assumptions=scenario.assumptions,
    )
    gates = dict(scenario.gate_satisfaction)
    if scenario.supplier_offer is None:
        gates["exact_sku"] = False
    if not isinstance(scenario.customer_facing_promise, str) or not scenario.customer_facing_promise.strip():
        gates["customer_facing_promise"] = False
    promotion = evaluate_promotion(
        scenario.candidate_id,
        "scale_candidate",
        gate_satisfaction=gates,
        evidence_state=scenario.evidence_state,
        ownership=scenario.ownership,
    )
    achievable_index = STAGES.index(promotion.achievable_stage)
    reached_launch = achievable_index >= STAGES.index("launch_draft")
    reached_experiment = achievable_index >= STAGES.index("experiment_ready")

    steps: list[DryRunStepResult] = [
        DryRunStepResult("evidence", "simulated", {"evidence_state": scenario.evidence_state}),
        DryRunStepResult(
            "supplier_offer", "simulated",
            {
                "supplier_permission_satisfied": bool(gates.get("supplier_permission", False)),
                "supplier_offer": scenario.supplier_offer.to_dict() if scenario.supplier_offer else None,
            },
        ),
        DryRunStepResult(
            "market_lane", "simulated",
            {
                "lane_id": scenario.lane.lane_id,
                "destination": scenario.lane.destination_country,
                "currency": scenario.lane.currency,
                "shipping_assumptions": {
                    name: value.to_dict()
                    for name in ("supplier_shipping", "domestic_shipping", "international_shipping")
                    if (value := getattr(scenario.assumptions, name)) is not None
                },
            },
        ),
        DryRunStepResult(
            "unit_economics", "simulated",
            {
                "contribution_margin": str(economics.contribution_margin) if economics.contribution_margin is not None else "unknown",
                "contribution_before_cac": economics.contribution_before_cac.to_dict(),
                "missing_inputs": list(economics.missing_inputs),
            },
        ),
        DryRunStepResult("competition", "simulated", scenario.competition.to_dict()),
        DryRunStepResult(
            "promotion_gate", "simulated",
            {"achievable_stage": promotion.achievable_stage, "blockers": list(promotion.blockers)},
        ),
    ]
    for step in LIFECYCLE_STEPS[_OFFER_STEP_INDEX:_EXPERIMENT_STEP_INDEX]:
        if reached_launch:
            steps.append(DryRunStepResult(step, "draft", {"stage": promotion.achievable_stage}))
        else:
            steps.append(DryRunStepResult(step, "blocked_upstream", {}, reasons=promotion.blockers))
    for step in LIFECYCLE_STEPS[_EXPERIMENT_STEP_INDEX:]:
        if reached_experiment:
            steps.append(DryRunStepResult(step, "simulated", {"stage": promotion.achievable_stage}))
        else:
            steps.append(DryRunStepResult(step, "blocked_upstream", {}, reasons=promotion.blockers))

    packet = {
        "scenario_id": scenario.scenario_id,
        "workspace_id": scenario.workspace_id,
        "business_model": scenario.business_model.value,
        "supplier_offer": scenario.supplier_offer.to_dict() if scenario.supplier_offer else None,
        "market_lane": scenario.lane.to_dict(),
        "shipping_assumptions": {
            name: value.to_dict()
            for name in ("supplier_shipping", "domestic_shipping", "international_shipping")
            if (value := getattr(scenario.assumptions, name)) is not None
        },
        "customer_facing_promise": scenario.customer_facing_promise if isinstance(scenario.customer_facing_promise, str) and scenario.customer_facing_promise else None,
        "evidence_state": scenario.evidence_state,
        "assumptions": _assumptions_payload(scenario.assumptions),
        "blockers": list(promotion.blockers),
        "economics": economics.to_dict(),
        "launch_decision": "launch_draft_only" if reached_launch else "blocked",
        "dry_run": True,
        "live_actions_taken": False,
    }
    return DryRunLifecycleReport(
        scenario.scenario_id,
        scenario.candidate_id,
        promotion.achievable_stage,
        reached_launch,
        tuple(steps),
        economics,
        promotion,
        commerce_packet=packet,
    )


__all__ = ["LIFECYCLE_STEPS", "DryRunScenarioInput", "DryRunStepResult", "DryRunLifecycleReport", "run_dry_run_lifecycle"]
