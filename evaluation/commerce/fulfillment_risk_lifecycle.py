"""Deterministic, offline supplier-direct post-purchase risk lifecycle.

This module is an additive projection over the existing commerce dry-run
authority.  It models operational risk after a simulated order without
calling suppliers, carriers, payment systems, or customer channels.  Money
and reserve math stays in ``backend.economics.kernel``; events stay in the
canonical ``backend.contracts.events.Event`` envelope.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any, Mapping, Protocol, Sequence

from backend.contracts.events import Event
from backend.economics.kernel import (
    EVIDENCE_STATES,
    EvidenceRef,
    MarketLane,
    Money,
    UnitEconomicsAssumptions,
    UnitEconomicsResult,
)
from backend.events.repository import AppendResult, EventRepository

from .business_model_economics import calculate_offer_economics
from .canonical import (
    BusinessModel,
    CommercialOwnership,
    OwnershipAssignment,
    SupplierOfferIdentity,
    launch_blockers_for_ownership,
)


MAX_STATE_COUNT = 64
MAX_EVIDENCE_REFS = 32
MAX_FLAG_COUNT = 32
MAX_TEXT_LENGTH = 256
MAX_REPORT_BYTES = 64 * 1024
_FORBIDDEN_MARKERS = ("api_key", "access_token", "authorization", "password", "secret", "-----begin", "<html")

FULFILLMENT_STATES: tuple[str, ...] = (
    "order_received",
    "payment_authorized",
    "payment_captured",
    "supplier_order_drafted",
    "supplier_order_approved",
    "supplier_order_submitted",
    "supplier_accepted",
    "stock_confirmed",
    "tracking_pending",
    "in_transit",
    "delayed",
    "delivered",
    "failed_delivery",
    "cancelled",
    "return_requested",
    "rma_opened",
    "return_in_transit",
    "return_received",
    "refund_requested",
    "refund_completed",
    "replacement_requested",
    "replacement_shipped",
    "chargeback_opened",
    "chargeback_resolved",
    "contribution_reconciled",
)

# Compatibility with the existing 15-stage dry-run lifecycle.  This is a
# mapping, not a second state machine or a replacement for that authority.
LEGACY_STAGE_MAP: Mapping[str, str] = {
    "order_received": "simulated_order",
    "payment_authorized": "simulated_order",
    "payment_captured": "simulated_order",
    "supplier_order_drafted": "supplier_dispatch_draft",
    "supplier_order_approved": "supplier_dispatch_draft",
    "supplier_order_submitted": "supplier_dispatch_draft",
    "supplier_accepted": "supplier_dispatch_draft",
    "stock_confirmed": "supplier_dispatch_draft",
    "tracking_pending": "tracking_draft",
    "in_transit": "tracking_draft",
    "delayed": "tracking_draft",
    "delivered": "delivery",
    "failed_delivery": "delivery",
    "cancelled": "delivery",
    "return_requested": "return_rma",
    "rma_opened": "return_rma",
    "return_in_transit": "return_rma",
    "return_received": "return_rma",
    "refund_requested": "return_rma",
    "refund_completed": "return_rma",
    "replacement_requested": "return_rma",
    "replacement_shipped": "return_rma",
    "chargeback_opened": "return_rma",
    "chargeback_resolved": "return_rma",
    "contribution_reconciled": "contribution_reconciliation",
}

_TRANSITIONS: Mapping[str, frozenset[str]] = {
    "order_received": frozenset({"payment_authorized", "cancelled"}),
    "payment_authorized": frozenset({"payment_captured", "cancelled", "chargeback_opened"}),
    "payment_captured": frozenset({"supplier_order_drafted", "cancelled", "chargeback_opened"}),
    "supplier_order_drafted": frozenset({"supplier_order_approved", "cancelled"}),
    "supplier_order_approved": frozenset({"supplier_order_submitted", "cancelled"}),
    "supplier_order_submitted": frozenset({"supplier_accepted", "cancelled"}),
    "supplier_accepted": frozenset({"stock_confirmed", "cancelled"}),
    "stock_confirmed": frozenset({"tracking_pending", "cancelled"}),
    "tracking_pending": frozenset({"in_transit", "delayed", "cancelled"}),
    "in_transit": frozenset({"delayed", "delivered", "failed_delivery", "cancelled"}),
    "delayed": frozenset({"in_transit", "delivered", "failed_delivery", "cancelled"}),
    "delivered": frozenset({"return_requested", "replacement_requested", "refund_requested", "chargeback_opened", "contribution_reconciled"}),
    "failed_delivery": frozenset({"refund_requested", "replacement_requested", "cancelled", "chargeback_opened"}),
    "cancelled": frozenset({"refund_requested", "chargeback_opened", "contribution_reconciled"}),
    "return_requested": frozenset({"rma_opened", "refund_requested", "replacement_requested"}),
    "rma_opened": frozenset({"return_in_transit", "refund_requested", "replacement_requested"}),
    "return_in_transit": frozenset({"return_received", "delayed"}),
    "return_received": frozenset({"refund_requested", "replacement_requested", "contribution_reconciled"}),
    "refund_requested": frozenset({"refund_completed", "chargeback_opened", "contribution_reconciled"}),
    "refund_completed": frozenset({"contribution_reconciled"}),
    "replacement_requested": frozenset({"replacement_shipped", "refund_requested", "chargeback_opened"}),
    "replacement_shipped": frozenset({"tracking_pending", "in_transit", "delayed", "delivered"}),
    "chargeback_opened": frozenset({"chargeback_resolved"}),
    "chargeback_resolved": frozenset({"contribution_reconciled"}),
    "contribution_reconciled": frozenset(),
}

_PORT_NAMES: tuple[str, ...] = (
    "supplier_order",
    "tracking",
    "returns",
    "warranty",
    "supplier_communication",
)
_RETURN_STATES = frozenset({
    "return_requested", "rma_opened", "return_in_transit", "return_received",
    "refund_requested", "refund_completed", "replacement_requested", "replacement_shipped",
})
_NO_AUTHORITY_METADATA: Mapping[str, Any] = {
    "dry_run": True,
    "read_only": True,
    "advisory": True,
    "non_authoritative": True,
    "manual_approval_required": True,
    "live_action_allowed": False,
    "no_supplier_dispatch_authority": True,
    "no_tracking_mutation_authority": True,
    "no_return_mutation_authority": True,
    "no_payment_authority": True,
    "no_refund_authority": True,
    "no_customer_message_authority": True,
    "no_database_write_authority": True,
}


def _text(value: Any, field_name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()) or len(value) > MAX_TEXT_LENGTH:
        raise ValueError(f"invalid {field_name}")
    if any(ord(char) < 32 for char in value):
        raise ValueError(f"invalid {field_name}")
    return value


def _assert_safe_serialized(value: Any) -> None:
    serialized = canonical_json(value).lower()
    if any(marker in serialized for marker in _FORBIDDEN_MARKERS):
        raise ValueError("unsafe or raw credential/payload marker")


def _evidence_state(refs: Sequence[EvidenceRef], explicit: str) -> str:
    if explicit not in EVIDENCE_STATES:
        raise ValueError("invalid evidence_state")
    states = [explicit, *(ref.evidence_state for ref in refs)]
    if any(state == "missing" for state in states):
        return "missing"
    if any(state in {"unknown", "stale", "rejected"} for state in states):
        return "unknown"
    if any(state in {"fixture", "simulated", "assumed", "derived"} for state in states):
        return "assumed"
    if all(state == "verified" for state in states):
        return "verified"
    if any(state == "live_readonly" for state in states):
        return "live_readonly"
    return "observed"


@dataclass(frozen=True)
class FulfillmentResponsibilityMap:
    """Accountability and route contract for one simulated order."""

    ownership: CommercialOwnership
    customer_support_route: str = ""
    rma_escalation_route: str = ""
    supplier_response_sla: str = ""
    delivery_promise: str = ""
    return_destination: str = ""
    return_cost_payer: str = ""
    evidence_state: str = "unknown"
    evidence_refs: tuple[EvidenceRef, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.ownership, CommercialOwnership):
            raise ValueError("invalid ownership")
        for field_name in (
            "customer_support_route", "rma_escalation_route", "supplier_response_sla",
            "delivery_promise", "return_destination", "return_cost_payer",
        ):
            _text(getattr(self, field_name), field_name, allow_empty=True)
        if self.evidence_state not in EVIDENCE_STATES:
            raise ValueError("invalid evidence_state")
        if not isinstance(self.evidence_refs, tuple) or any(not isinstance(item, EvidenceRef) for item in self.evidence_refs):
            raise ValueError("invalid evidence_refs")
        if len(self.evidence_refs) > MAX_EVIDENCE_REFS:
            raise ValueError("too many evidence_refs")
        _assert_safe_serialized([item.to_dict() for item in self.evidence_refs])

    @property
    def blockers(self) -> tuple[str, ...]:
        missing = {
            "customer_support_route": self.customer_support_route,
            "rma_escalation_route": self.rma_escalation_route,
            "supplier_response_sla": self.supplier_response_sla,
            "delivery_promise": self.delivery_promise,
            "return_destination": self.return_destination,
            "return_cost_payer": self.return_cost_payer,
        }
        route_blockers = [f"missing_{name}" for name, value in missing.items() if not value.strip()]
        return tuple(sorted(set((*launch_blockers_for_ownership(self.ownership), *route_blockers))))

    def to_dict(self) -> dict[str, Any]:
        return {
            "ownership": self.ownership.to_dict(),
            "customer_support_route": self.customer_support_route,
            "rma_escalation_route": self.rma_escalation_route,
            "supplier_response_sla": self.supplier_response_sla,
            "delivery_promise": self.delivery_promise,
            "return_destination": self.return_destination,
            "return_cost_payer": self.return_cost_payer,
            "evidence_state": self.evidence_state,
            "evidence_refs": [item.to_dict() for item in self.evidence_refs],
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True)
class FulfillmentRiskScenario:
    """Sanitized input for one deterministic post-purchase simulation."""

    scenario_id: str
    order_id: str
    candidate_id: str
    workspace_id: str
    lane: MarketLane
    price: Money
    product_cost: Money
    assumptions: UnitEconomicsAssumptions
    responsibilities: FulfillmentResponsibilityMap
    state_path: tuple[str, ...]
    supplier_offer: SupplierOfferIdentity | None = None
    catalog_item_id: str = ""
    flags: tuple[str, ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = ()
    evidence_state: str = "unknown"

    def __post_init__(self) -> None:
        for field_name in ("scenario_id", "order_id", "candidate_id", "workspace_id"):
            _text(getattr(self, field_name), field_name)
        if not isinstance(self.lane, MarketLane) or not isinstance(self.price, Money) or not isinstance(self.product_cost, Money):
            raise ValueError("invalid economics inputs")
        if not isinstance(self.assumptions, UnitEconomicsAssumptions):
            raise ValueError("invalid assumptions")
        if not isinstance(self.responsibilities, FulfillmentResponsibilityMap):
            raise ValueError("invalid responsibilities")
        if not isinstance(self.state_path, tuple) or not self.state_path or len(self.state_path) > MAX_STATE_COUNT:
            raise ValueError("invalid state_path")
        if self.state_path[0] != "order_received" or any(state not in FULFILLMENT_STATES for state in self.state_path):
            raise ValueError("state_path must begin with order_received and use known states")
        for previous, current in zip(self.state_path, self.state_path[1:]):
            if current not in _TRANSITIONS[previous]:
                raise ValueError(f"invalid fulfillment transition: {previous} -> {current}")
        _text(self.catalog_item_id, "catalog_item_id", allow_empty=True)
        if not isinstance(self.flags, tuple) or len(self.flags) > MAX_FLAG_COUNT:
            raise ValueError("invalid flags")
        for item in self.flags:
            _text(item, "flag")
        if self.evidence_state not in EVIDENCE_STATES:
            raise ValueError("invalid evidence_state")
        if not isinstance(self.evidence_refs, tuple) or any(not isinstance(item, EvidenceRef) for item in self.evidence_refs):
            raise ValueError("invalid evidence_refs")
        if len(self.evidence_refs) > MAX_EVIDENCE_REFS:
            raise ValueError("too many evidence_refs")
        _assert_safe_serialized(self.to_dict())

    @property
    def current_state(self) -> str:
        return self.state_path[-1]

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "order_id": self.order_id,
            "candidate_id": self.candidate_id,
            "workspace_id": self.workspace_id,
            "lane": self.lane.to_dict(),
            "price": self.price.to_dict(),
            "product_cost": self.product_cost.to_dict(),
            "state_path": list(self.state_path),
            "supplier_offer": self.supplier_offer.to_dict() if self.supplier_offer else None,
            "catalog_item_id": self.catalog_item_id,
            "flags": list(self.flags),
            "evidence_state": self.evidence_state,
            "evidence_refs": [item.to_dict() for item in self.evidence_refs],
        }


@dataclass(frozen=True)
class PortObservation:
    """Sanitized result from an explicitly offline adapter."""

    capability: str
    status: str = "unavailable"
    evidence_state: str = "unknown"
    evidence_id: str = ""
    detail_code: str = ""

    def __post_init__(self) -> None:
        _text(self.capability, "capability")
        if self.status not in {"simulated", "unavailable", "blocked"}:
            raise ValueError("invalid port status")
        if self.evidence_state not in EVIDENCE_STATES:
            raise ValueError("invalid port evidence_state")
        _text(self.evidence_id, "evidence_id", allow_empty=True)
        _text(self.detail_code, "detail_code", allow_empty=True)

    def to_dict(self) -> dict[str, str]:
        return {
            "capability": self.capability,
            "status": self.status,
            "evidence_state": self.evidence_state,
            "evidence_id": self.evidence_id,
            "detail_code": self.detail_code,
        }


class SupplierOrderPort(Protocol):
    def supplier_order(self, *, order_id: str) -> PortObservation: ...


class TrackingPort(Protocol):
    def tracking(self, *, order_id: str) -> PortObservation: ...


class ReturnsPort(Protocol):
    def returns(self, *, order_id: str) -> PortObservation: ...


class WarrantyPort(Protocol):
    def warranty(self, *, order_id: str) -> PortObservation: ...


class SupplierCommunicationPort(Protocol):
    def supplier_communication(self, *, order_id: str) -> PortObservation: ...


class FulfillmentPortBundle(Protocol):
    """Composition boundary for replacing all offline port adapters."""

    def supplier_order(self, *, order_id: str) -> PortObservation: ...
    def tracking(self, *, order_id: str) -> PortObservation: ...
    def returns(self, *, order_id: str) -> PortObservation: ...
    def warranty(self, *, order_id: str) -> PortObservation: ...
    def supplier_communication(self, *, order_id: str) -> PortObservation: ...


class FixtureFulfillmentAdapter:
    """Pure fixture adapter implementing all five replaceable ports."""

    def __init__(self, observations: Mapping[str, PortObservation] | None = None) -> None:
        values = dict(observations or {})
        unknown = set(values) - set(_PORT_NAMES)
        if unknown:
            raise ValueError("unknown fixture capabilities")
        self._observations = values

    @classmethod
    def complete(cls) -> "FixtureFulfillmentAdapter":
        return cls({
            name: PortObservation(name, "simulated", "fixture", f"fixture:{name}:v1", "fixture_observation")
            for name in _PORT_NAMES
        })

    def _inspect(self, capability: str, *, order_id: str) -> PortObservation:
        _text(order_id, "order_id")
        return self._observations.get(capability, PortObservation(capability, detail_code="fixture_observation_missing"))

    def supplier_order(self, *, order_id: str) -> PortObservation:
        return self._inspect("supplier_order", order_id=order_id)

    def tracking(self, *, order_id: str) -> PortObservation:
        return self._inspect("tracking", order_id=order_id)

    def returns(self, *, order_id: str) -> PortObservation:
        return self._inspect("returns", order_id=order_id)

    def warranty(self, *, order_id: str) -> PortObservation:
        return self._inspect("warranty", order_id=order_id)

    def supplier_communication(self, *, order_id: str) -> PortObservation:
        return self._inspect("supplier_communication", order_id=order_id)


@dataclass(frozen=True)
class FulfillmentRiskReport:
    scenario_id: str
    order_id: str
    candidate_id: str
    workspace_id: str
    current_state: str
    state_path: tuple[str, ...]
    status: str
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    next_human_action: str
    responsibility_map: FulfillmentResponsibilityMap
    evidence_state: str
    evidence_refs: tuple[EvidenceRef, ...]
    sla_risks: tuple[str, ...]
    reserve_classifications: tuple[str, ...]
    risk_flags: tuple[str, ...]
    economics: UnitEconomicsResult
    port_observations: tuple[PortObservation, ...]
    events: tuple[Event, ...] = ()
    dry_run: bool = True
    live_action_allowed: bool = False
    provider_calls: bool = False
    credentials_used: bool = False
    external_mutations: bool = False
    database_writes: bool = False

    def __post_init__(self) -> None:
        if not self.dry_run or self.live_action_allowed or self.provider_calls or self.credentials_used:
            raise ValueError("fulfillment risk reports are offline dry-runs only")
        if self.external_mutations or self.database_writes:
            raise ValueError("fulfillment risk reports cannot claim mutations")
        if self.status not in {"simulated", "hold", "blocked"}:
            raise ValueError("invalid report status")
        if self.evidence_state not in EVIDENCE_STATES:
            raise ValueError("invalid report evidence_state")
        if len(self.evidence_refs) > MAX_EVIDENCE_REFS:
            raise ValueError("too many report evidence_refs")

    def to_dict(self) -> dict[str, Any]:
        result = {
            "schema": "MarketOS.FulfillmentRiskDryRun.v1",
            "scenario_id": self.scenario_id,
            "order_id": self.order_id,
            "candidate_id": self.candidate_id,
            "workspace_id": self.workspace_id,
            "current_state": self.current_state,
            "legacy_stage": LEGACY_STAGE_MAP[self.current_state],
            "state_path": list(self.state_path),
            "status": self.status,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "next_human_action": self.next_human_action,
            "responsibility_map": self.responsibility_map.to_dict(),
            "evidence_state": self.evidence_state,
            "evidence_refs": [item.to_dict() for item in self.evidence_refs],
            "sla_risks": list(self.sla_risks),
            "reserve_classifications": list(self.reserve_classifications),
            "risk_flags": list(self.risk_flags),
            "economics": self.economics.to_dict(),
            "port_observations": [item.to_dict() for item in self.port_observations],
            "event_ids": [item.event_id for item in self.events],
            "event_replay_hashes": [item.replay_hash() for item in self.events],
            "dry_run": self.dry_run,
            "live_action_allowed": self.live_action_allowed,
            "provider_calls": self.provider_calls,
            "credentials_used": self.credentials_used,
            "external_mutations": self.external_mutations,
            "database_writes": self.database_writes,
        }
        serialized = canonical_json(result)
        _assert_safe_serialized(result)
        if len(serialized.encode("utf-8")) > MAX_REPORT_BYTES:
            raise ValueError("fulfillment risk report exceeds output bound")
        return result

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json(self.to_dict()).encode("utf-8")).hexdigest()

    def canonical_json(self) -> str:
        return canonical_json(self.to_dict())


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _required_ports(scenario: FulfillmentRiskScenario) -> tuple[str, ...]:
    states = set(scenario.state_path)
    required = {"supplier_order", "supplier_communication"}
    if states & {"tracking_pending", "in_transit", "delayed", "delivered", "failed_delivery", "replacement_shipped"}:
        required.add("tracking")
    if states & _RETURN_STATES:
        required.add("returns")
    if "replacement_requested" in states:
        required.add("warranty")
    return tuple(name for name in _PORT_NAMES if name in required)


def _observe_ports(scenario: FulfillmentRiskScenario, adapter: FulfillmentPortBundle | None) -> tuple[PortObservation, ...]:
    methods = {
        "supplier_order": "supplier_order",
        "tracking": "tracking",
        "returns": "returns",
        "warranty": "warranty",
        "supplier_communication": "supplier_communication",
    }
    observations: list[PortObservation] = []
    for capability in _required_ports(scenario):
        if adapter is None:
            observations.append(PortObservation(capability, detail_code="offline_adapter_not_supplied"))
            continue
        observations.append(getattr(adapter, methods[capability])(order_id=scenario.order_id))
    return tuple(observations)


def _supplier_flags(scenario: FulfillmentRiskScenario) -> tuple[str, ...]:
    flags: set[str] = set()
    if scenario.supplier_offer is None:
        flags.add("supplier_proof_missing")
        if scenario.catalog_item_id:
            flags.add("catalog_is_not_supplier_proof")
    elif scenario.supplier_offer.evidence_ref is None:
        flags.add("supplier_offer_evidence_missing")
    elif scenario.supplier_offer.evidence_ref.evidence_state not in {"observed", "live_readonly", "verified"}:
        flags.add("supplier_proof_fixture_only")
    return tuple(sorted(flags))


def _risk_flags(scenario: FulfillmentRiskScenario, current_state: str, observations: Sequence[PortObservation]) -> tuple[str, ...]:
    flags = set(scenario.flags) | set(_supplier_flags(scenario))
    if current_state == "tracking_pending" and any(item.capability == "tracking" and item.status != "simulated" for item in observations):
        flags.add("tracking_not_observed")
    if current_state == "delayed":
        flags.add("delivery_promise_at_risk")
    if current_state in {"failed_delivery", "cancelled"}:
        flags.add("customer_resolution_exposure")
    if current_state in _RETURN_STATES:
        flags.add("reverse_logistics_exposure")
    if "chargeback_opened" in scenario.state_path:
        flags.add("chargeback_exposure")
    return tuple(sorted(flags))


def _reserve_classifications(economics: UnitEconomicsResult, state_path: Sequence[str], flags: Sequence[str]) -> tuple[str, ...]:
    reserves = {f"unknown_cost:{item}" for item in economics.missing_inputs}
    if set(state_path) & _RETURN_STATES:
        reserves.add("return_reserve_exposure")
    if "replacement_requested" in state_path:
        reserves.add("replacement_cost_exposure")
    if "chargeback_opened" in state_path:
        reserves.add("chargeback_reserve_exposure")
    if "damaged_shipment_supplier_reimbursement" in flags:
        reserves.add("supplier_reimbursement_unknown")
    return tuple(sorted(reserves))


def _sla_risks(scenario: FulfillmentRiskScenario, current_state: str, observations: Sequence[PortObservation]) -> tuple[str, ...]:
    risks: set[str] = set()
    if current_state in {"tracking_pending", "delayed"}:
        risks.add("tracking_or_delivery_sla")
    if current_state == "delayed":
        risks.add("delivery_promise_breach_review")
    if any(item.capability == "supplier_communication" and item.status != "simulated" for item in observations):
        risks.add("supplier_response_sla_unavailable")
    if not scenario.responsibilities.supplier_response_sla.strip():
        risks.add("supplier_response_sla_missing")
    return tuple(sorted(risks))


def _next_action(status: str, current_state: str, blockers: Sequence[str], flags: Sequence[str]) -> str:
    if blockers:
        return f"resolve:{blockers[0]}"
    if "tracking_not_observed" in flags:
        return "confirm_tracking_or_escalate_supplier"
    if current_state == "delayed":
        return "confirm_revised_delivery_promise_and_support_route"
    if current_state in {"return_requested", "rma_opened", "return_in_transit"}:
        return "confirm_return_authorization_and_customer_route"
    if current_state in {"refund_requested", "chargeback_opened"}:
        return "reconcile_refund_or_chargeback_owner_and_timing"
    if current_state == "contribution_reconciled":
        return "archive_sanitized_evidence_and_review_next_scenario"
    return "operator_review_next_human_transition"


def project_fulfillment_events(report: FulfillmentRiskReport, *, occurred_at: float = 0.0) -> tuple[Event, ...]:
    """Project a report to the existing canonical event envelope."""
    events: list[Event] = [
        Event(
            f"{report.scenario_id}:started",
            report.workspace_id,
            "commerce_fulfillment_risk",
            report.order_id,
            "fulfillment_risk_started",
            1,
            occurred_at,
            correlation_id=report.scenario_id,
            source="evaluation.commerce.fulfillment_risk_lifecycle",
            payload={"scenario_id": report.scenario_id, "order_id": report.order_id, "candidate_id": report.candidate_id},
            metadata=dict(_NO_AUTHORITY_METADATA),
        )
    ]
    for index, state in enumerate(report.state_path, start=1):
        events.append(
            Event(
                f"{report.scenario_id}:{index:03d}:{state}",
                report.workspace_id,
                "commerce_fulfillment_risk",
                report.order_id,
                f"fulfillment_risk_{state}",
                1,
                occurred_at + index / 1000,
                causation_id=events[-1].event_id,
                correlation_id=report.scenario_id,
                source="evaluation.commerce.fulfillment_risk_lifecycle",
                payload={
                    "state": state,
                    "legacy_stage": LEGACY_STAGE_MAP[state],
                    "state_index": index,
                    "risk_flags": list(report.risk_flags),
                },
                metadata={
                    **_NO_AUTHORITY_METADATA,
                    "idempotency_key": f"{report.scenario_id}:{index:03d}:{state}",
                    "evidence_ids": [item.evidence_id for item in report.evidence_refs],
                },
            )
        )
    events.append(
        Event(
            f"{report.scenario_id}:completed",
            report.workspace_id,
            "commerce_fulfillment_risk",
            report.order_id,
            "fulfillment_risk_completed",
            1,
            occurred_at + (len(report.state_path) + 1) / 1000,
            causation_id=events[-1].event_id,
            correlation_id=report.scenario_id,
            source="evaluation.commerce.fulfillment_risk_lifecycle",
            payload={
                "current_state": report.current_state,
                "status": report.status,
                "blockers": list(report.blockers),
                "next_human_action": report.next_human_action,
            },
            metadata={**_NO_AUTHORITY_METADATA, "evidence_ids": [item.evidence_id for item in report.evidence_refs]},
        )
    )
    return tuple(events)


def run_fulfillment_risk_dry_run(
    scenario: FulfillmentRiskScenario,
    *,
    adapter: FulfillmentPortBundle | None = None,
    occurred_at: float = 0.0,
) -> FulfillmentRiskReport:
    """Evaluate one scenario without performing an external action."""
    if not isinstance(occurred_at, (int, float)) or occurred_at < 0:
        raise ValueError("occurred_at must be a non-negative deterministic epoch")
    economics = calculate_offer_economics(
        BusinessModel.RETAIL_MARGIN,
        price=scenario.price,
        product_cost=scenario.product_cost,
        lane=scenario.lane,
        assumptions=scenario.assumptions,
    )
    all_refs = tuple(dict.fromkeys((*scenario.evidence_refs, *scenario.responsibilities.evidence_refs, *economics.evidence_refs)))
    evidence_state = _evidence_state(all_refs, scenario.evidence_state)
    observations = _observe_ports(scenario, adapter)
    blockers = set(scenario.responsibilities.blockers)
    if scenario.flags and "conflicting_supplier_terms" in scenario.flags:
        blockers.add("conflicting_supplier_terms")
    if "supplier_proof_missing" in _supplier_flags(scenario):
        blockers.add("supplier_proof_missing")
    for observation in observations:
        if observation.status == "blocked":
            blockers.add(f"blocked_{observation.capability}")
        elif observation.status == "unavailable":
            blockers.add(f"unavailable_{observation.capability}")
    risk_flags = _risk_flags(scenario, scenario.current_state, observations)
    warnings = set(risk_flags) - blockers
    status = "blocked" if blockers else "simulated"
    if not blockers and any(item.status != "simulated" for item in observations):
        status = "hold"
    report = FulfillmentRiskReport(
        scenario.scenario_id,
        scenario.order_id,
        scenario.candidate_id,
        scenario.workspace_id,
        scenario.current_state,
        scenario.state_path,
        status,
        tuple(sorted(blockers)),
        tuple(sorted(warnings)),
        _next_action(status, scenario.current_state, sorted(blockers), risk_flags),
        scenario.responsibilities,
        evidence_state,
        all_refs,
        _sla_risks(scenario, scenario.current_state, observations),
        _reserve_classifications(economics, scenario.state_path, scenario.flags),
        risk_flags,
        economics,
        observations,
    )
    return replace(report, events=project_fulfillment_events(report, occurred_at=occurred_at))


def append_report_events(report: FulfillmentRiskReport, repository: EventRepository) -> tuple[AppendResult, ...]:
    """Append only to an explicitly supplied local event repository."""
    return tuple(repository.append_many(report.events))


SCENARIO_NAMES: tuple[str, ...] = (
    "successful_direct_shipment",
    "tracking_never_arrives",
    "shipment_delayed",
    "stock_cancellation_after_payment",
    "wrong_sku_missing_accessory",
    "damaged_shipment_supplier_reimbursement",
    "customer_return_merchant_paid",
    "warranty_replacement",
    "refund_lag_chargeback",
    "unsupported_missing_route",
    "conflicting_supplier_terms",
)


def _fixture_evidence(scenario_id: str) -> EvidenceRef:
    return EvidenceRef(
        f"fixture:{scenario_id}:v1",
        source_type="fixture",
        extraction_method="fixture",
        evidence_state="fixture",
        origin="CN",
        destination="MX",
        captured_at="2026-01-01T00:00:00+00:00",
    )


def build_named_scenario(name: str) -> FulfillmentRiskScenario:
    """Build a sanitized named fixture for the operator CLI and tests."""
    if name not in SCENARIO_NAMES:
        raise ValueError(f"unknown scenario: {name}")
    evidence = _fixture_evidence(name)
    lane = MarketLane(
        "cn-mx-demo", "CN", "CN", "fixture-warehouse", "MX", "CDMX", currency="MXN",
        return_destination="fixture-return-destination", delivery_promise="5-10 business days",
        evidence_refs=(evidence,),
    )
    ownership = CommercialOwnership(*(OwnershipAssignment(role, "fixture-owner", evidence) for role in (
        "merchant_of_record", "fulfillment_owner", "warranty_owner", "return_owner", "support_owner", "payment_collection_owner",
    )), commission_or_margin_method="retail_margin")
    responsibilities = FulfillmentResponsibilityMap(
        ownership=ownership,
        customer_support_route="fixture://support",
        rma_escalation_route="fixture://rma",
        supplier_response_sla="48h",
        delivery_promise="5-10 business days",
        return_destination="fixture-return-destination",
        return_cost_payer="merchant",
        evidence_state="fixture",
        evidence_refs=(evidence,),
    )
    assumptions = UnitEconomicsAssumptions(
        supplier_shipping=Money("80", "MXN", source="fixture", provenance="fixture", evidence_state="fixture", evidence_ref=evidence),
        return_rate=Decimal("0.05"), defect_rate=Decimal("0.02"), warranty_rate=Decimal("0.02"),
        support_reserve_rate=Decimal("0.01"), chargeback_rate=Decimal("0.01"), refund_lag_days=Decimal("14"),
        evidence_refs=(evidence,),
    )
    common = (
        "order_received", "payment_authorized", "payment_captured", "supplier_order_drafted",
        "supplier_order_approved", "supplier_order_submitted", "supplier_accepted", "stock_confirmed", "tracking_pending",
    )
    paths: Mapping[str, tuple[str, ...]] = {
        "successful_direct_shipment": (*common, "in_transit", "delivered", "contribution_reconciled"),
        "tracking_never_arrives": common,
        "shipment_delayed": (*common, "delayed"),
        "stock_cancellation_after_payment": ("order_received", "payment_authorized", "payment_captured", "cancelled", "refund_requested"),
        "wrong_sku_missing_accessory": (*common, "in_transit", "delivered", "return_requested", "rma_opened", "return_in_transit", "return_received", "replacement_requested", "replacement_shipped", "delivered", "contribution_reconciled"),
        "damaged_shipment_supplier_reimbursement": (*common, "in_transit", "delivered", "return_requested", "rma_opened", "return_in_transit", "return_received", "refund_requested", "refund_completed", "contribution_reconciled"),
        "customer_return_merchant_paid": (*common, "in_transit", "delivered", "return_requested", "rma_opened", "return_in_transit", "return_received", "refund_requested", "refund_completed", "contribution_reconciled"),
        "warranty_replacement": (*common, "in_transit", "delivered", "replacement_requested", "replacement_shipped", "delivered", "contribution_reconciled"),
        "refund_lag_chargeback": (*common, "in_transit", "delivered", "refund_requested", "chargeback_opened", "chargeback_resolved", "contribution_reconciled"),
        "unsupported_missing_route": ("order_received", "payment_authorized", "payment_captured"),
        "conflicting_supplier_terms": (*common, "in_transit", "delivered"),
    }
    route_overrides = {} if name != "unsupported_missing_route" else {"customer_support_route": "", "rma_escalation_route": ""}
    responsibilities = replace(responsibilities, **route_overrides)
    flags = ()
    if name == "damaged_shipment_supplier_reimbursement":
        flags = ("damaged_shipment_supplier_reimbursement",)
    if name == "conflicting_supplier_terms":
        flags = ("conflicting_supplier_terms",)
    offer = SupplierOfferIdentity("fixture-supplier", f"offer-{name}", "SKU-FIXTURE", evidence_ref=evidence)
    return FulfillmentRiskScenario(
        name, f"order-{name}", f"candidate-{name}", "workspace-fulfillment-dry-run", lane,
        Money("999", "MXN", source="fixture", provenance="fixture", evidence_state="fixture", evidence_ref=evidence),
        Money("400", "MXN", source="fixture", provenance="fixture", evidence_state="fixture", evidence_ref=evidence),
        assumptions, responsibilities, paths[name], offer, "catalog-fixture-item", flags, (evidence,), "fixture",
    )


def build_named_adapter(name: str) -> FixtureFulfillmentAdapter:
    """Return the bounded fixture adapter for one named scenario."""
    if name not in SCENARIO_NAMES:
        raise ValueError(f"unknown scenario: {name}")
    observations = {
        capability: PortObservation(capability, "simulated", "fixture", f"fixture:{capability}:v1", "fixture_observation")
        for capability in _PORT_NAMES
    }
    if name == "tracking_never_arrives":
        observations["tracking"] = PortObservation(
            "tracking", "unavailable", "unknown", detail_code="tracking_not_received"
        )
    return FixtureFulfillmentAdapter(observations)


__all__ = [
    "FULFILLMENT_STATES", "LEGACY_STAGE_MAP", "MAX_REPORT_BYTES", "SCENARIO_NAMES",
    "FulfillmentResponsibilityMap", "FulfillmentRiskScenario", "PortObservation",
    "SupplierOrderPort", "TrackingPort", "ReturnsPort", "WarrantyPort", "SupplierCommunicationPort",
    "FulfillmentPortBundle",
    "FixtureFulfillmentAdapter", "FulfillmentRiskReport", "canonical_json", "project_fulfillment_events",
    "run_fulfillment_risk_dry_run", "append_report_events", "build_named_scenario", "build_named_adapter",
]
