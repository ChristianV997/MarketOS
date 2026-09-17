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

from dataclasses import dataclass
from typing import Any, Mapping

from backend.economics.kernel import MarketLane, Money, UnitEconomicsAssumptions, UnitEconomicsResult

from .business_model_economics import calculate_offer_economics
from .canonical import BusinessModel, CommercialOwnership, CompetitionSnapshot
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
        }


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
    promotion = evaluate_promotion(
        scenario.candidate_id,
        "scale_candidate",
        gate_satisfaction=scenario.gate_satisfaction,
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
            {"supplier_permission_satisfied": bool(scenario.gate_satisfaction.get("supplier_permission", False))},
        ),
        DryRunStepResult(
            "market_lane", "simulated",
            {"lane_id": scenario.lane.lane_id, "destination": scenario.lane.destination_country, "currency": scenario.lane.currency},
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

    return DryRunLifecycleReport(
        scenario.scenario_id,
        scenario.candidate_id,
        promotion.achievable_stage,
        reached_launch,
        tuple(steps),
        economics,
        promotion,
    )


__all__ = ["LIFECYCLE_STEPS", "DryRunScenarioInput", "DryRunStepResult", "DryRunLifecycleReport", "run_dry_run_lifecycle"]
