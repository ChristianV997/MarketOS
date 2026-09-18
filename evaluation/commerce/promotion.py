"""Evidence-driven promotion state machine for canonical commerce offers.

Implements the progression the integration spec requires:

    candidate -> evidence_collected -> supplier_terms_pending ->
    economics_screened -> market_lane_validated -> supplier_validated ->
    launch_draft -> experiment_ready -> live_sales_validated ->
    scale_candidate

A fixture or manual-import evidence state may support screening but must
never advance a candidate past ``economics_screened`` — it cannot become
supplier-approved, profitable, validated, launch-ready, or scale-ready
without evidence in a live/observed/verified state (see
``backend.economics.kernel.EVIDENCE_STATES``).

This module does not re-score evidence or call a provider; it is a pure,
deterministic gate evaluator over evidence already supplied by the caller,
matching the "thin decision layer" convention used by
``evaluation.commerce.opportunity_synthesis``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from backend.economics.kernel import EVIDENCE_STATES

from .canonical import CommercialOwnership, PromotionGate, RiskState, launch_blockers_for_ownership

STAGES: tuple[str, ...] = (
    "candidate",
    "evidence_collected",
    "supplier_terms_pending",
    "economics_screened",
    "market_lane_validated",
    "supplier_validated",
    "launch_draft",
    "experiment_ready",
    "live_sales_validated",
    "scale_candidate",
)

# The explicit gates the spec requires, in a stable canonical order.
GATE_IDS: tuple[str, ...] = (
    "exact_sku",
    "destination_lane",
    "shipping",
    "return_route",
    "warranty_route",
    "support_owner",
    "supplier_permission",
    "compliance",
    "economics",
    "competition",
    "customer_facing_promise",
)

# Gates that must be satisfied to be *at* a given stage (cumulative by design:
# every gate required by an earlier stage stays required at every later one).
_STAGE_GATES: dict[str, tuple[str, ...]] = {
    "candidate": (),
    "evidence_collected": ("exact_sku",),
    "supplier_terms_pending": ("exact_sku", "supplier_permission"),
    "economics_screened": ("exact_sku", "supplier_permission", "economics"),
    "market_lane_validated": ("exact_sku", "supplier_permission", "economics", "destination_lane", "shipping"),
    "supplier_validated": ("exact_sku", "supplier_permission", "economics", "destination_lane", "shipping", "compliance"),
    "launch_draft": (
        "exact_sku", "supplier_permission", "economics", "destination_lane", "shipping",
        "compliance", "return_route", "warranty_route", "support_owner", "customer_facing_promise",
    ),
    "experiment_ready": (
        "exact_sku", "supplier_permission", "economics", "destination_lane", "shipping",
        "compliance", "return_route", "warranty_route", "support_owner", "customer_facing_promise",
        "competition",
    ),
}
_STAGE_GATES["live_sales_validated"] = _STAGE_GATES["experiment_ready"]
_STAGE_GATES["scale_candidate"] = _STAGE_GATES["experiment_ready"]

# Stages that require ownership (merchant_of_record/fulfillment/warranty/
# return/support/payment_collection) to be fully known — launch and beyond.
_OWNERSHIP_REQUIRED_FROM_INDEX = STAGES.index("launch_draft")

# Fixture/manual-import evidence cannot advance a candidate past this stage,
# regardless of which gates are marked satisfied.
FIXTURE_EVIDENCE_CEILING = "economics_screened"
_LIVE_EVIDENCE_STATES = {"observed", "live_readonly", "verified"}


def max_stage_for_evidence_state(evidence_state: str) -> str:
    """The highest stage reachable given an aggregate evidence state.

    Any state other than the kernel's live/observed/verified states is
    treated as fixture/manual/unknown for promotion purposes — screening
    value only, never a supplier/launch/scale authorization.
    """
    if evidence_state not in EVIDENCE_STATES:
        evidence_state = "unknown"
    return STAGES[-1] if evidence_state in _LIVE_EVIDENCE_STATES else FIXTURE_EVIDENCE_CEILING


@dataclass(frozen=True)
class PromotionDecision:
    candidate_id: str
    requested_stage: str
    achievable_stage: str
    promoted: bool
    gates: tuple[PromotionGate, ...]
    risk: RiskState
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "requested_stage": self.requested_stage,
            "achievable_stage": self.achievable_stage,
            "promoted": self.promoted,
            "gates": [gate.to_dict() for gate in self.gates],
            "risk": self.risk.to_dict(),
            "blockers": list(self.blockers),
        }


def evaluate_promotion(
    candidate_id: str,
    requested_stage: str,
    *,
    gate_satisfaction: Mapping[str, bool],
    evidence_state: str = "unknown",
    ownership: CommercialOwnership | None = None,
) -> PromotionDecision:
    """Evaluate whether ``candidate_id`` may advance to ``requested_stage``.

    ``gate_satisfaction`` maps a subset of ``GATE_IDS`` to whether the
    caller has evidence satisfying that gate; unlisted gates are treated as
    unsatisfied (fail-closed, never assumed true).
    """
    if requested_stage not in STAGES:
        raise ValueError(f"unknown promotion stage: {requested_stage}")
    ownership = ownership or CommercialOwnership.unknown()

    evidence_ceiling = max_stage_for_evidence_state(evidence_state)
    ceiling_index = STAGES.index(evidence_ceiling)

    def _unmet_for(stage: str) -> tuple[str, ...]:
        return tuple(gate_id for gate_id in _STAGE_GATES[stage] if not gate_satisfaction.get(gate_id, False))

    def _ownership_blockers_for(stage_index: int) -> tuple[str, ...]:
        return launch_blockers_for_ownership(ownership) if stage_index >= _OWNERSHIP_REQUIRED_FROM_INDEX else ()

    # _STAGE_GATES is cumulative by construction (each stage's required gates
    # is a superset of every earlier stage's), so the achievable stage is
    # simply the highest stage, up to the evidence ceiling, whose own gate
    # and ownership requirements are all met.
    achievable_index = 0
    for index, stage in enumerate(STAGES):
        if index > ceiling_index or _unmet_for(stage) or _ownership_blockers_for(index):
            break
        achievable_index = index
    achievable_stage = STAGES[achievable_index]

    requested_index = STAGES.index(requested_stage)
    required = _STAGE_GATES[requested_stage]
    gates = tuple(
        PromotionGate(
            gate_id=gate_id,
            required=gate_id in required,
            satisfied=bool(gate_satisfaction.get(gate_id, False)),
            reason="" if gate_satisfaction.get(gate_id, False) else "no_evidence_supplied",
        )
        for gate_id in GATE_IDS
    )
    unmet_gates = _unmet_for(requested_stage)
    ownership_blockers = _ownership_blockers_for(requested_index)
    evidence_blocked = requested_index > ceiling_index

    blockers = list(unmet_gates) + list(ownership_blockers)
    if evidence_blocked:
        blockers.append(f"evidence_state_insufficient_for_stage:{evidence_state}")

    promoted = achievable_index >= requested_index and not blockers

    if not promoted:
        level = "blocked" if requested_index >= STAGES.index("supplier_validated") else "high" if unmet_gates or ownership_blockers else "medium"
    else:
        level = "low"
    risk = RiskState(level=level, blockers=tuple(sorted(set(blockers))), open_gates=unmet_gates, evidence_state=evidence_state)
    return PromotionDecision(candidate_id, requested_stage, achievable_stage, promoted, gates, risk, tuple(sorted(set(blockers))))


__all__ = [
    "STAGES",
    "GATE_IDS",
    "FIXTURE_EVIDENCE_CEILING",
    "PromotionDecision",
    "evaluate_promotion",
    "max_stage_for_evidence_state",
]
