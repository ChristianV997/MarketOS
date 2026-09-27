"""Offline service-market evidence composition over canonical MarketOS authorities.

This adapter normalizes bounded observations, delegates money arithmetic to
``backend.economics.kernel``, records one canonical event, and exports only
TrustOS-approved status metadata. It is not a market scorer or launch gate.
"""
from __future__ import annotations

import hashlib
import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

from backend.contracts.events import Event
from backend.economics.kernel import (
    CurrencyMismatchError,
    EVIDENCE_STATES,
    EconomicsError,
    EvidenceRef,
    MarketLane,
    Money,
    ServiceEconomics,
    calculate_service_economics,
    canonical_json,
)
from backend.events.replay_certification import replay_summary
from backend.events.repository import InMemoryEventRepository
from backend.workspaces.client_workspace import ClientWorkspace
from backend.workspaces.registry import WorkspaceRegistry
from evaluation.commerce.promotion import evaluate_promotion
from evaluation.trustos.client_workspace_isolation import (
    ClientWorkspaceEvidenceExport,
    ClientWorkspaceExportError,
    export_client_evidence,
)

MAX_MARKET_OBSERVATIONS = 100
MAX_EVIDENCE_REFERENCES = 200
MAX_EVENT_PAYLOAD_BYTES = 64_000
MAX_INPUT_BYTES = 64_000
MAX_RUN_REPORT_BYTES = 128_000
INPUT_CONTRACT_ID = "MarketOS.ServiceMarketResearchInput.v1"
RUN_REPORT_SCHEMA = "MarketOS.ServiceMarketResearchRun.v1"
OFFERING_TYPES = frozenset({"service", "goods", "hybrid", "unknown"})
EVIDENCE_SOURCE_CLASSES = frozenset({"fixture", "manual", "unknown", "observed", "live_validated"})
EVIDENCE_CLASSES = EVIDENCE_SOURCE_CLASSES | {"derived"}
EVIDENCE_SOURCE_MODES = frozenset({"fixture", "manual", "unknown", "observed"})
EVIDENCE_STATE_CLAIMS = EVIDENCE_STATES | {"manual", "live_validated", "not_assessed", "not_applicable"}
MARKET_ACCESS_CLAIMS = frozenset({"not_assessed", "not_applicable", "observed", "live_validated"})
_PRIVILEGED_STATE_CLAIMS = frozenset({"verified", "live_readonly", "live_validated"})
_SAFE_PRIVILEGED_CLAIM = "unverified_privileged_claim"
_SAFE_MONEY_PROVENANCE = frozenset({
    "assumed", "derived", "explicit_fx", "fixture", "manual", "observed", "unknown", "unverified_claim",
})
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SECRET_SHAPE = re.compile(r"(?i)(?:\b(?:sk|pk|ghp|gho|ghu|ghs|ghr)[_-][A-Za-z0-9_-]{8,}\b|\bAKIA[0-9A-Z]{16}\b)")
_UNSAFE_IDENTIFIER = re.compile(
    r"(?i)(?:internal[_-]prompt|formula|heuristic|cross[_-]client|other[_-]client|"
    r"raw[_-](?:provider[_-])?payload|provider[_-]response|credential|password|secret|source[_-]code)"
)
_DIGEST = re.compile(r"^(?:[0-9a-fA-F]{64}|[0-9a-fA-F]{128})$")
_UNAVAILABLE_STATES = frozenset({"missing", "unknown", "stale", "rejected"})
_COST_FIELDS = ("delivery_cost", "tooling_cost", "pass_through_cost", "refund_revision_reserve")
_TOP_LEVEL_FIELDS = frozenset({
    "contract_id", "candidate_id", "offering_type", "workspace_id", "as_of",
    "market_access", "market_lane", "observations", "economics",
})
_REFERENCE_FIELDS = frozenset({
    "evidence_id", "source_type", "source_url", "document_ref", "captured_at",
    "valid_until", "evidence_state_claim", "confidence", "snapshot_hash",
})
_EVIDENCE_FIELDS = frozenset({"class", "reference"})
_MONEY_FIELDS = frozenset({"amount", "currency", "uncertainty", "evidence"})
_LANE_FIELDS = frozenset({
    "lane_id", "origin", "ship_from", "warehouse", "destination_country", "currency", "evidence",
})
_ECONOMICS_FIELDS = frozenset({
    "service_fee", "labor_cost", "tooling_cost", "pass_through_cost", "refund_revision_reserve",
    "delivery_hours", "delivery_evidence", "capacity_hours", "capacity_evidence",
})
_MARKET_ACCESS_FIELDS = frozenset({"applicability_claim", "evidence"})
_OBSERVATION_FIELDS = frozenset({"metric", "subject_id", "value", "unit", "uncertainty", "evidence"})


@dataclass(frozen=True)
class ServiceMarketObservation:
    """One normalized market fact anchored to the canonical evidence identity."""

    metric: str
    subject_id: str
    value: Decimal | Money
    unit: str
    evidence_ref: EvidenceRef
    uncertainty: Decimal | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.metric, str) or self.metric not in {"demand", "competitor_price"}:
            raise ValueError("unsupported service-market observation metric")
        _require_identifier(self.subject_id, "observation subject")
        _require_identifier(self.unit, "observation unit")
        if not isinstance(self.evidence_ref, EvidenceRef):
            raise ValueError("observation evidence reference is required")
        if self.uncertainty is not None:
            object.__setattr__(self, "uncertainty", _decimal(self.uncertainty, "observation uncertainty"))
        if self.metric == "competitor_price":
            if not isinstance(self.value, Money) or self.value.currency != self.unit:
                raise ValueError("competitor price requires currency-matched Money")
            if self.value.amount < 0:
                raise ValueError("competitor price cannot be negative")
            if (
                self.value.evidence_ref is None
                or self.value.evidence_ref.evidence_id != self.evidence_ref.evidence_id
                or self.value.evidence_state != self.evidence_ref.evidence_state
            ):
                raise ValueError("competitor price evidence identity mismatch")
        else:
            if isinstance(self.value, bool) or isinstance(self.value, Money):
                raise ValueError("demand observation must be a non-negative Decimal")
            try:
                value = Decimal(str(self.value))
            except (InvalidOperation, ValueError):
                raise ValueError("demand observation is malformed") from None
            if not value.is_finite() or value < 0:
                raise ValueError("demand observation must be a non-negative Decimal")
            object.__setattr__(self, "value", value)


@dataclass(frozen=True)
class _ParsedEvidence:
    reference: EvidenceRef
    evidence_class: str
    state_claim: str
    unverified_privileged_claim: bool
    claim_fingerprint: str


@dataclass(frozen=True)
class _ParsedInput:
    candidate_id: str
    offering_type: str
    workspace: ClientWorkspace
    as_of: datetime
    market_access_claim: str
    market_access_evidence: tuple[EvidenceRef, ...]
    lane: MarketLane
    observations: tuple[ServiceMarketObservation, ...]
    economics: Mapping[str, Any]
    evidence_source_mode: str
    evidence_classes: Mapping[str, str]
    state_claims: Mapping[str, str]
    unverified_privileged_claims: frozenset[str]


def _strict_object(value: Any, fields: frozenset[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    actual = set(value)
    missing = fields - actual
    unexpected = actual - fields
    if missing:
        raise ValueError(f"{label} is missing required fields")
    if unexpected:
        raise ValueError(f"{label} contains unexpected fields")
    return value


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise ValueError("non-finite JSON numbers are not accepted")


def load_input_document(path: str | Path) -> dict[str, Any]:
    """Read one bounded JSON contract file without retaining its source path."""
    try:
        with Path(path).open("rb") as source:
            raw = source.read(MAX_INPUT_BYTES + 1)
    except (OSError, TypeError, ValueError):
        raise ValueError("unable to read service-market input") from None
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("service-market input size limit exceeded")
    try:
        decoded = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_strict_json_object,
            parse_constant=_reject_json_constant,
        )
    except ValueError as exc:
        if str(exc) == "duplicate JSON field":
            raise
        raise ValueError("service-market input JSON is malformed") from None
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        raise ValueError("service-market input JSON is malformed") from None
    return dict(_strict_object(decoded, _TOP_LEVEL_FIELDS, "input document"))


def _parse_evidence(value: Any, label: str, *, source_mode: str) -> _ParsedEvidence:
    wrapper = _strict_object(value, _EVIDENCE_FIELDS, f"{label} evidence")
    class_claim = wrapper["class"]
    if not isinstance(class_claim, str) or class_claim not in EVIDENCE_SOURCE_CLASSES:
        raise ValueError(f"{label} evidence class is invalid")
    raw = _strict_object(wrapper["reference"], _REFERENCE_FIELDS, f"{label} evidence reference")
    state_claim = raw["evidence_state_claim"]
    allowed_claims = EVIDENCE_STATE_CLAIMS
    if not isinstance(state_claim, str) or state_claim not in allowed_claims:
        raise ValueError(f"{label} evidence state claim is invalid")
    if not isinstance(source_mode, str) or source_mode not in EVIDENCE_SOURCE_MODES:
        raise ValueError("evidence source mode is invalid")
    privileged_claim = class_claim == "live_validated" or state_claim in _PRIVILEGED_STATE_CLAIMS
    if state_claim in {"manual", "not_assessed", "not_applicable"} or state_claim in _PRIVILEGED_STATE_CLAIMS:
        canonical_state = "unknown"
    else:
        canonical_state = state_claim
    effective_class = source_mode
    if source_mode == "observed" and canonical_state != "observed":
        effective_class = "unknown"
    safe_state_claim = _SAFE_PRIVILEGED_CLAIM if privileged_claim else state_claim
    evidence_id = _require_identifier(raw["evidence_id"], f"{label} evidence")
    source_type = _require_identifier(raw["source_type"], f"{label} evidence source")
    for key in ("source_url", "document_ref"):
        if not isinstance(raw[key], str) or len(raw[key].encode("utf-8")) > 512:
            raise ValueError(f"{label} evidence locator is malformed")
        if _SECRET_SHAPE.search(raw[key]):
            raise ValueError(f"{label} evidence locator contains a secret-shaped value")
    snapshot_hash = raw["snapshot_hash"]
    if not isinstance(snapshot_hash, str) or (snapshot_hash and _DIGEST.fullmatch(snapshot_hash) is None):
        raise ValueError(f"{label} evidence snapshot digest is malformed")
    confidence = raw["confidence"]
    if confidence in (None, "unknown"):
        confidence_value = None
    else:
        confidence_value = _decimal(confidence, f"{label} evidence confidence")
        if confidence_value > 1:
            raise ValueError(f"{label} evidence confidence is outside the accepted range")
    try:
        reference = EvidenceRef(
            evidence_id=evidence_id,
            source_type=source_type,
            source_url=raw["source_url"],
            document_ref=raw["document_ref"],
            captured_at=raw["captured_at"],
            valid_until=raw["valid_until"],
            evidence_state=canonical_state,
            confidence=confidence_value,
            extraction_method="bounded_manual_fixture_contract",
            snapshot_hash=snapshot_hash,
            human_confirmed=False,
        )
    except (TypeError, ValueError):
        raise ValueError(f"{label} evidence reference is malformed") from None
    safe_class_claim = _SAFE_PRIVILEGED_CLAIM if class_claim == "live_validated" else class_claim
    claim_fingerprint = hashlib.sha256(f"{safe_class_claim}\n{safe_state_claim}".encode("utf-8")).hexdigest()
    return _ParsedEvidence(reference, effective_class, safe_state_claim, privileged_claim, claim_fingerprint)


def _parse_money(value: Any, label: str, *, source_mode: str) -> tuple[Money | None, _ParsedEvidence | None]:
    if value is None:
        return None, None
    raw = _strict_object(value, _MONEY_FIELDS, f"{label} money")
    parsed_evidence = _parse_evidence(raw["evidence"], label, source_mode=source_mode)
    provenance = parsed_evidence.evidence_class
    try:
        money = Money(
            raw["amount"],
            raw["currency"],
            source=f"{parsed_evidence.evidence_class}_import",
            uncertainty=raw["uncertainty"],
            evidence_ref=parsed_evidence.reference,
            provenance=provenance,
            evidence_state=parsed_evidence.reference.evidence_state,
        )
    except (TypeError, ValueError):
        raise ValueError(f"{label} money is malformed") from None
    return money, parsed_evidence


def _require_identifier(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or _IDENTIFIER.fullmatch(value) is None
        or ".." in value
        or _SECRET_SHAPE.search(value) is not None
        or _UNSAFE_IDENTIFIER.search(value) is not None
    ):
        raise ValueError(f"invalid {label} identifier")
    return value


def _decimal(value: Any, label: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"invalid {label}")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"invalid {label}") from None
    if not result.is_finite() or result < 0:
        raise ValueError(f"invalid {label}")
    return result


def _aware_datetime(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        raise ValueError(f"{label} must be a timezone-aware ISO timestamp") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must be a timezone-aware ISO timestamp")
    return parsed


def _safe_evidence_state(state: Any) -> str:
    if not isinstance(state, str) or state not in EVIDENCE_STATES or state in _PRIVILEGED_STATE_CLAIMS:
        return "unknown"
    return state


def _safe_state_claim(claim: Any, fallback: str) -> str:
    if claim == _SAFE_PRIVILEGED_CLAIM:
        return _SAFE_PRIVILEGED_CLAIM
    if not isinstance(claim, str) or claim not in EVIDENCE_STATE_CLAIMS:
        return fallback
    if claim in _PRIVILEGED_STATE_CLAIMS:
        return _SAFE_PRIVILEGED_CLAIM
    return claim


def _reference_summary(ref: EvidenceRef) -> dict[str, Any]:
    if (
        len(ref.source_url.encode("utf-8")) > 512
        or len(ref.document_ref.encode("utf-8")) > 512
        or len(ref.captured_at) > 64
        or len(ref.valid_until) > 64
        or len(ref.snapshot_hash) > 128
    ):
        raise ValueError("evidence locator exceeds size limit")
    if ref.snapshot_hash and _DIGEST.fullmatch(ref.snapshot_hash) is None:
        raise ValueError("evidence snapshot digest is malformed")
    if _SECRET_SHAPE.search(ref.source_url) or _SECRET_SHAPE.search(ref.document_ref):
        raise ValueError("evidence locator contains a secret-shaped value")
    locator = ""
    if ref.source_url or ref.document_ref:
        locator = hashlib.sha256(f"{ref.source_url}\n{ref.document_ref}".encode("utf-8")).hexdigest()
    return {
        "evidence_id": _require_identifier(ref.evidence_id, "evidence"),
        "source_type": _require_identifier(ref.source_type, "evidence source"),
        "evidence_state": _safe_evidence_state(ref.evidence_state),
        "captured_at": ref.captured_at,
        "valid_until": ref.valid_until,
        "confidence": str(ref.confidence) if ref.confidence is not None else "unknown",
        "snapshot_hash": ref.snapshot_hash,
        "locator_sha256": locator,
    }


def _money_summary(value: Money) -> dict[str, str]:
    if value.provenance not in _SAFE_MONEY_PROVENANCE:
        raise ValueError("money provenance is not an approved label")
    exchange_timestamp = value.exchange_rate_timestamp or "unknown"
    if value.exchange_rate_timestamp:
        exchange_timestamp = _aware_datetime(value.exchange_rate_timestamp, "exchange-rate timestamp").isoformat()
    return {
        "amount": str(value.amount),
        "currency": value.currency,
        "provenance": value.provenance,
        "evidence_state": _safe_evidence_state(value.evidence_state),
        "evidence_id": value.evidence_ref.evidence_id if value.evidence_ref else "",
        "uncertainty": str(value.uncertainty) if value.uncertainty is not None else "unknown",
        "exchange_rate": str(value.exchange_rate) if value.exchange_rate is not None else "unknown",
        "exchange_rate_timestamp": exchange_timestamp,
    }


def _evidence_class(ref: EvidenceRef, source_mode: str = "unknown") -> str:
    if not isinstance(source_mode, str) or source_mode not in EVIDENCE_SOURCE_MODES:
        raise ValueError("evidence source mode is invalid")
    if source_mode == "observed" and _safe_evidence_state(ref.evidence_state) != "observed":
        return "unknown"
    return source_mode


def _evidence_blockers(refs: tuple[EvidenceRef, ...], as_of: datetime) -> list[str]:
    blockers: list[str] = []
    for ref in refs:
        evidence_id = _require_identifier(ref.evidence_id, "evidence")
        if ref.evidence_state in _UNAVAILABLE_STATES:
            blockers.append(f"{ref.evidence_state}_evidence:{evidence_id}")
        if ref.evidence_state in _PRIVILEGED_STATE_CLAIMS:
            blockers.append(f"unverified_privileged_evidence_claim:{evidence_id}")
        if not ref.captured_at or not ref.valid_until:
            blockers.append(f"freshness_not_assessed:{evidence_id}")
            continue
        captured = _aware_datetime(ref.captured_at, "evidence captured_at")
        valid_until = _aware_datetime(ref.valid_until, "evidence valid_until")
        if captured > valid_until:
            raise ValueError("evidence freshness interval is malformed")
        if captured > as_of:
            blockers.append(f"future_dated_evidence:{evidence_id}")
        elif valid_until < as_of:
            blockers.append(f"stale_evidence:{evidence_id}")
    return blockers


def _observation_conflict_blockers(
    observations: tuple[ServiceMarketObservation, ...],
) -> list[str]:
    observed_by_fact: dict[tuple[str, str], tuple[str, str]] = {}
    blockers: list[str] = []
    for item in observations:
        key = (item.metric, item.subject_id)
        value = _observation_value(item)
        previous = observed_by_fact.get(key)
        if previous is not None and previous != value:
            blockers.append(f"conflicting_observation:{item.metric}:{item.subject_id}")
        else:
            observed_by_fact[key] = value
    return blockers


def _reference_evidence_summary(
    ref: EvidenceRef,
    source_mode: str,
    state_claims: Mapping[str, str] | None,
) -> dict[str, Any]:
    summary = _reference_summary(ref)
    summary["evidence_class"] = _evidence_class(ref, source_mode)
    claim = state_claims.get(ref.evidence_id, ref.evidence_state) if state_claims is not None else ref.evidence_state
    summary["state_claim"] = _safe_state_claim(claim, _safe_evidence_state(ref.evidence_state))
    return summary


def _observation_value(observation: ServiceMarketObservation) -> tuple[Decimal, str]:
    if isinstance(observation.value, Money):
        return observation.value.amount, observation.value.currency
    return observation.value, observation.unit


def _lane_summary(lane: MarketLane | None) -> dict[str, str] | None:
    if lane is None:
        return None
    def safe_label(value: str, label: str) -> str:
        if not isinstance(value, str) or len(value) > 80 or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]*", value) is None or ".." in value:
            raise ValueError(f"invalid {label} label")
        return value

    return {
        "lane_id": _require_identifier(lane.lane_id, "market lane"),
        "origin": safe_label(lane.origin, "market origin"),
        "ship_from": safe_label(lane.ship_from, "service origin"),
        "warehouse": safe_label(lane.warehouse, "service delivery mode"),
        "destination_country": safe_label(lane.destination_country, "market jurisdiction"),
        "currency": lane.currency,
    }


def _registered_workspace(
    workspace: ClientWorkspace,
    registry: WorkspaceRegistry,
) -> ClientWorkspace:
    """Return the exact registry record or fail before composing any output."""
    if not isinstance(workspace, ClientWorkspace) or not isinstance(registry, WorkspaceRegistry):
        raise ClientWorkspaceExportError("invalid_metadata")
    try:
        registered = registry.get(workspace.workspace_id)
    except Exception:
        raise ClientWorkspaceExportError("identity_rejected") from None
    if registered is None or registered.to_dict() != workspace.to_dict():
        raise ClientWorkspaceExportError("identity_rejected")
    return registered


def _promotion_summary(
    *,
    candidate_id: str,
    economics: ServiceEconomics | None,
    observations: tuple[ServiceMarketObservation, ...],
    lane: MarketLane | None,
    delivery_cost: Money | None,
    delivery_evidence: EvidenceRef | None,
    blockers: list[str],
    evidence_source_mode: str,
) -> dict[str, Any]:
    """Project this adapter's evidence into the canonical promotion gate."""
    blocker_set = set(blockers)
    def evidence_usable(ref: EvidenceRef | None) -> bool:
        if not isinstance(ref, EvidenceRef):
            return False
        if ref.evidence_state in _UNAVAILABLE_STATES or _evidence_class(ref, evidence_source_mode) == "unknown":
            return False
        evidence_id = ref.evidence_id
        return not any(
            f"{prefix}:{evidence_id}" in blocker_set
            for prefix in (
                "stale_evidence",
                "future_dated_evidence",
                "freshness_not_assessed",
                "unknown_evidence_source",
                "unverified_privileged_evidence_claim",
                "malformed_evidence_state_mismatch",
            )
        )

    lane_ready = (
        lane is not None
        and bool(lane.evidence_refs)
        and all(evidence_usable(ref) for ref in lane.evidence_refs)
        and "market_lane_not_assessed" not in blocker_set
        and "missing_market_lane_evidence" not in blocker_set
    )
    shipping_ready = (
        isinstance(delivery_cost, Money)
        and evidence_usable(delivery_evidence)
    )
    competition_ready = any(
        item.metric == "competitor_price"
        and evidence_usable(item.evidence_ref)
        for item in observations
    ) and not any(item.startswith("conflicting_observation:") for item in blockers)
    decision = evaluate_promotion(
        candidate_id,
        "launch_draft",
        gate_satisfaction={
            # The service contract has no exact SKU, ownership, return,
            # warranty, support, compliance, or customer-promise proof.
            "exact_sku": False,
            "destination_lane": lane_ready,
            "shipping": shipping_ready,
            "return_route": False,
            "warranty_route": False,
            "support_owner": False,
            "supplier_permission": False,
            "compliance": False,
            "economics": economics is not None,
            "competition": competition_ready,
            "customer_facing_promise": False,
        },
        evidence_state=economics.evidence_state if economics is not None else "unknown",
    )
    return decision.to_dict()


def _record_assessment(
    *,
    payload: dict[str, Any],
    workspace: ClientWorkspace,
    registry: WorkspaceRegistry,
    as_of: datetime,
    export_blockers: list[str],
    required_evidence: list[str],
    missing_inputs: list[str],
    event_type: str = "service_market_assessment_recorded",
    aggregate_type: str = "service_market_candidate",
) -> tuple[Event, ClientWorkspaceEvidenceExport, dict[str, Any]]:
    workspace = _registered_workspace(workspace, registry)
    canonical_payload = canonical_json(payload)
    if len(canonical_payload.encode("utf-8")) > MAX_EVENT_PAYLOAD_BYTES:
        raise ValueError("service-market event payload exceeds size limit")
    identity = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()
    event = Event(
        event_id=f"{'service-market' if aggregate_type == 'service_market_candidate' else 'market-research'}:{payload['candidate_id']}:{identity[:20]}",
        workspace_id=workspace.workspace_id,
        aggregate_type=aggregate_type,
        aggregate_id=payload["candidate_id"],
        event_type=event_type,
        schema_version=1,
        occurred_at=as_of.timestamp(),
        correlation_id=identity,
        source="evaluation.companyos.service_market_research",
        payload=payload,
        metadata={
            "dry_run": True,
            "read_only": True,
            "advisory": True,
            "non_authoritative": True,
            "execution_class": "actual_executed",
            "evidence_classes": payload["evidence_classes"],
            "decision_class": "simulated_or_planned",
            "live_actions_taken": False,
            "provider_calls": False,
            "database_writes": False,
            "payments_or_orders": False,
            "publishing_or_messaging": False,
        },
    )
    repository = InMemoryEventRepository()
    repository.append(event)
    replayed = repository.replay(aggregate_id=payload["candidate_id"])
    replay = replay_summary(replayed)
    if replay["sequence_issues"] or replay["live_authority_violations"] or len(replayed) != 1:
        raise ValueError("market-research event replay certification failed")

    blockers = list(dict.fromkeys(export_blockers))
    if "market_access_applicability_review" not in required_evidence:
        required_evidence.append("market_access_applicability_review")
    export_status = "needs_evidence" if blockers else "requires_review"
    trustos_payload = {
        "workspace_id": workspace.workspace_id,
        "status": export_status,
        "blockers": blockers,
        "evidence_required": list(dict.fromkeys(required_evidence)),
        "approvals_required": ["human_review_before_commercial_action"],
        "next_actions": [
            "Review the bounded market evidence and its provenance.",
            "Assess market-access applicability with the appropriate human reviewer.",
        ],
    }
    evidence_state = "missing" if missing_inputs or blockers else "requires_review"
    trustos_export = export_client_evidence(
        workspace=workspace,
        registry=registry,
        provenance=f"derived://{'service-market' if aggregate_type == 'service_market_candidate' else 'market-research'}/{identity[:24]}",
        evidence_state=evidence_state,
        payload=trustos_payload,
    )
    return event, trustos_export, replay


def assess_service_market_candidate(
    *,
    candidate_id: str,
    offering_type: str,
    service_fee: Money | None,
    delivery_cost: Money | None,
    tooling_cost: Money | None,
    pass_through_cost: Money | None,
    refund_revision_reserve: Money | None,
    delivery_hours: Decimal | int | str | float | None,
    delivery_evidence: EvidenceRef | None,
    capacity_hours: Decimal | int | str | float | None,
    capacity_evidence: EvidenceRef | None,
    observations: tuple[ServiceMarketObservation, ...],
    lane: MarketLane | None,
    market_access_evidence: tuple[EvidenceRef, ...],
    market_access_claim: str = "not_assessed",
    evidence_source_mode: str = "unknown",
    evidence_classes: Mapping[str, str] | None = None,
    evidence_state_claims: Mapping[str, str] | None = None,
    unverified_privileged_claims: frozenset[str] = frozenset(),
    workspace: ClientWorkspace,
    registry: WorkspaceRegistry,
    as_of: datetime,
) -> tuple[ServiceEconomics | None, Event, ClientWorkspaceEvidenceExport]:
    """Assess one service candidate without producing a score or launch decision.

    Goods must continue through their existing product authorities. Missing
    service cost inputs prevent economics from being computed; explicit zero
    costs are accepted only when they carry their own evidence reference.
    """
    candidate_id = _require_identifier(candidate_id, "candidate")
    if offering_type != "service":
        raise ValueError("service-only assessment requires offering_type='service'")
    if not isinstance(market_access_claim, str) or market_access_claim not in MARKET_ACCESS_CLAIMS | {_SAFE_PRIVILEGED_CLAIM}:
        raise ValueError("market-access applicability claim is invalid")
    if not isinstance(evidence_source_mode, str) or evidence_source_mode not in EVIDENCE_SOURCE_MODES:
        raise ValueError("evidence source mode is invalid")
    if evidence_classes is not None and (
        not isinstance(evidence_classes, Mapping)
        or len(evidence_classes) > MAX_EVIDENCE_REFERENCES
        or any(
                not isinstance(key, str)
                or _IDENTIFIER.fullmatch(key) is None
                or not isinstance(value, str)
                or value not in EVIDENCE_CLASSES
                for key, value in evidence_classes.items()
            )
    ):
        raise ValueError("evidence-class map is malformed")
    if evidence_state_claims is not None and (
        not isinstance(evidence_state_claims, Mapping)
        or len(evidence_state_claims) > MAX_EVIDENCE_REFERENCES
        or any(
            not isinstance(key, str)
            or _IDENTIFIER.fullmatch(key) is None
            or not isinstance(value, str)
            or value not in EVIDENCE_STATE_CLAIMS | {_SAFE_PRIVILEGED_CLAIM}
            for key, value in evidence_state_claims.items()
        )
    ):
        raise ValueError("evidence-state claim map is malformed")
    if not isinstance(unverified_privileged_claims, frozenset) or len(unverified_privileged_claims) > MAX_EVIDENCE_REFERENCES:
        raise ValueError("unverified evidence-claim set is malformed")
    if any(not isinstance(key, str) or _IDENTIFIER.fullmatch(key) is None for key in unverified_privileged_claims):
        raise ValueError("unverified evidence-claim set is malformed")
    if market_access_claim == "live_validated":
        market_access_claim = _SAFE_PRIVILEGED_CLAIM
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    workspace = _registered_workspace(workspace, registry)
    if not isinstance(observations, tuple) or len(observations) > MAX_MARKET_OBSERVATIONS:
        raise ValueError("service-market observation limit exceeded")
    if any(not isinstance(item, ServiceMarketObservation) for item in observations):
        raise ValueError("service-market observations must be normalized typed values")
    if not isinstance(market_access_evidence, tuple):
        raise ValueError("market-access evidence must be a tuple")
    if any(not isinstance(ref, EvidenceRef) for ref in market_access_evidence):
        raise ValueError("market-access evidence reference is invalid")
    if lane is not None and not isinstance(lane, MarketLane):
        raise ValueError("market lane is invalid")

    blockers: list[str] = []
    missing_inputs: list[str] = []
    money_inputs = {
        "service_fee": service_fee,
        "delivery_cost": delivery_cost,
        "tooling_cost": tooling_cost,
        "pass_through_cost": pass_through_cost,
        "refund_revision_reserve": refund_revision_reserve,
    }
    for name, value in money_inputs.items():
        if value is None:
            missing_inputs.append(name)
            blockers.append(f"missing_{name}_evidence")
        elif not isinstance(value, Money):
            raise ValueError(f"{name} must be Money")
        elif (
            value.evidence_ref is None
            or value.evidence_state in _UNAVAILABLE_STATES
            or value.provenance == "unknown"
            or _evidence_class(value.evidence_ref, evidence_source_mode) == "unknown"
        ):
            missing_inputs.append(name)
            blockers.append(f"missing_{name}_evidence")
        elif value.evidence_ref.evidence_state != value.evidence_state:
            blockers.append(f"malformed_evidence_state_mismatch:{name}")
    if service_fee is not None and isinstance(service_fee, Money) and service_fee.amount <= 0:
        raise EconomicsError("service fee must be positive")

    hours = None if delivery_hours is None else _decimal(delivery_hours, "delivery hours")
    capacity = None if capacity_hours is None else _decimal(capacity_hours, "capacity hours")
    if hours is None:
        missing_inputs.append("delivery_hours")
        blockers.append("missing_delivery_hours_evidence")
    elif hours <= 0:
        raise EconomicsError("delivery hours must be positive")
    if capacity is None:
        missing_inputs.append("capacity_hours")
        blockers.append("missing_capacity_evidence")
    if delivery_evidence is None:
        missing_inputs.append("delivery_hours")
        blockers.append("missing_delivery_hours_evidence")
    elif not isinstance(delivery_evidence, EvidenceRef):
        raise ValueError("delivery-hours evidence reference is invalid")
    if capacity_evidence is None:
        missing_inputs.append("capacity_hours")
        blockers.append("missing_capacity_evidence")
    elif not isinstance(capacity_evidence, EvidenceRef):
        raise ValueError("capacity evidence reference is invalid")

    metrics = {item.metric for item in observations}
    if "demand" not in metrics:
        missing_inputs.append("market_demand")
        blockers.append("missing_market_demand_observation")
    if "competitor_price" not in metrics:
        missing_inputs.append("competitor_pricing")
        blockers.append("missing_competitor_price_observation")

    blockers.extend(_observation_conflict_blockers(observations))

    evidence_refs: list[EvidenceRef] = [item.evidence_ref for item in observations]
    financial_evidence_refs: list[EvidenceRef] = []
    for value in money_inputs.values():
        if isinstance(value, Money) and value.evidence_ref is not None:
            evidence_refs.append(value.evidence_ref)
            financial_evidence_refs.append(value.evidence_ref)
    evidence_refs.extend(ref for ref in (delivery_evidence, capacity_evidence) if isinstance(ref, EvidenceRef))
    if isinstance(delivery_evidence, EvidenceRef):
        financial_evidence_refs.append(delivery_evidence)
    evidence_refs.extend(market_access_evidence)
    if lane is not None:
        evidence_refs.extend(lane.evidence_refs)
    if len(evidence_refs) > MAX_EVIDENCE_REFERENCES:
        raise ValueError("service-market evidence reference limit exceeded")
    evidence_ids = {_require_identifier(ref.evidence_id, "evidence") for ref in evidence_refs}
    claim_ids = set((evidence_classes or {}).keys()) | set((evidence_state_claims or {}).keys()) | set(unverified_privileged_claims)
    if claim_ids - evidence_ids:
        raise ValueError("evidence claim references an unknown evidence id")
    privileged_claim_ids = set(unverified_privileged_claims)
    privileged_claim_ids.update(
        key for key, value in (evidence_classes or {}).items() if value == "live_validated"
    )
    privileged_claim_ids.update(
        key for key, value in (evidence_state_claims or {}).items()
        if value in _PRIVILEGED_STATE_CLAIMS | {_SAFE_PRIVILEGED_CLAIM}
    )
    state_claim_mismatch_ids = {
        ref.evidence_id
        for ref in evidence_refs
        if (evidence_state_claims or {}).get(ref.evidence_id) is not None
        and (evidence_state_claims or {}).get(ref.evidence_id) not in _PRIVILEGED_STATE_CLAIMS | {_SAFE_PRIVILEGED_CLAIM}
        and (evidence_state_claims or {}).get(ref.evidence_id) != ref.evidence_state
    }
    for ref in evidence_refs:
        _reference_summary(ref)
    all_evidence_blockers = _evidence_blockers(tuple(evidence_refs), as_of)
    blockers.extend(all_evidence_blockers)
    for ref in evidence_refs:
        evidence_class = _evidence_class(ref, evidence_source_mode)
        if ref.evidence_id in state_claim_mismatch_ids:
            blockers.append(f"malformed_evidence_state_mismatch:{ref.evidence_id}")
        if ref.evidence_id in privileged_claim_ids:
            blockers.append(f"unverified_privileged_evidence_claim:{ref.evidence_id}")
        elif evidence_class == "unknown":
            blockers.append(f"unknown_evidence_source:{ref.evidence_id}")
    capacity_evidence_usable = (
        capacity is not None
        and isinstance(capacity_evidence, EvidenceRef)
        and not _evidence_blockers((capacity_evidence,), as_of)
        and capacity_evidence.evidence_state not in _UNAVAILABLE_STATES
        and capacity_evidence.evidence_id not in state_claim_mismatch_ids
        and capacity_evidence.evidence_id not in privileged_claim_ids
    )

    if lane is None:
        blockers.append("market_lane_not_assessed")
    elif not lane.evidence_refs:
        missing_inputs.append("market_lane_evidence")
        blockers.append("missing_market_lane_evidence")
    elif service_fee is not None and lane.currency != service_fee.currency:
        raise CurrencyMismatchError()

    if service_fee is not None and isinstance(service_fee, Money):
        for item in observations:
            if isinstance(item.value, Money) and item.value.currency != service_fee.currency:
                raise CurrencyMismatchError()
        for name, value in money_inputs.items():
            if isinstance(value, Money) and value.currency != service_fee.currency:
                raise CurrencyMismatchError()

    if hours is not None and capacity_evidence_usable and capacity is not None and capacity < hours:
        blockers.append("insufficient_delivery_capacity")

    if market_access_claim == "not_assessed":
        blockers.append("market_access_not_assessed")
    else:
        blockers.append(f"market_access_claim_requires_review:{market_access_claim}")

    capacity_assessment = "not_assessed"
    if hours is not None and capacity is not None and capacity_evidence_usable:
        capacity_assessment = "insufficient" if capacity < hours else "evidence_recorded_capacity_adequate"

    blockers = list(dict.fromkeys(blockers))
    missing_inputs = list(dict.fromkeys(missing_inputs))
    economics: ServiceEconomics | None = None
    required_costs_present = all(isinstance(money_inputs[name], Money) for name in _COST_FIELDS)
    fee_evidence_present = isinstance(service_fee, Money) and service_fee.evidence_ref is not None
    financial_input_missing = any(
        name in missing_inputs
        for name in (*_COST_FIELDS, "service_fee", "delivery_hours")
    )
    financial_state_mismatch = any(
        item == f"malformed_evidence_state_mismatch:{name}"
        for name in (*_COST_FIELDS, "service_fee")
        for item in blockers
    )
    financial_evidence_blockers = _evidence_blockers(tuple(financial_evidence_refs), as_of)
    financial_evidence_blockers.extend(
        f"unverified_privileged_evidence_claim:{ref.evidence_id}"
        for ref in financial_evidence_refs
        if ref.evidence_id in privileged_claim_ids
        or _evidence_class(ref, evidence_source_mode) == "unknown"
    )
    financial_evidence_blockers.extend(
        f"malformed_evidence_state_mismatch:{ref.evidence_id}"
        for ref in financial_evidence_refs
        if ref.evidence_id in state_claim_mismatch_ids
    )
    if (
        fee_evidence_present
        and required_costs_present
        and hours is not None
        and not financial_input_missing
        and delivery_evidence is not None
        and not financial_state_mismatch
        and not financial_evidence_blockers
    ):
        economics = calculate_service_economics(
            candidate_id,
            service_fee,
            delivery_hours=hours,
            capacity_hours=capacity if capacity_evidence_usable else None,
            evidence_refs=tuple(financial_evidence_refs),
            delivery_cost=delivery_cost,
            tooling_cost=tooling_cost,
            pass_through_cost=pass_through_cost,
            refund_revision_reserve=refund_revision_reserve,
        )

    unresolved_checks = ["market_access_applicability"]
    evidence_issue_prefixes = (
        "missing_", "stale_evidence:", "future_dated_evidence:", "freshness_not_assessed:",
        "unknown_evidence:", "rejected_evidence:", "conflicting_observation:",
        "unknown_evidence_source:", "malformed_evidence_state_mismatch:", "market_lane_not_assessed",
        "market_access_", "unverified_privileged_evidence_claim:",
    )
    if any(item.startswith(evidence_issue_prefixes) for item in blockers):
        recommendation = "defer_for_evidence"
    elif "insufficient_delivery_capacity" in blockers:
        recommendation = "defer_for_capacity"
    elif economics is None or economics.contribution is None or economics.contribution.amount <= 0:
        recommendation = "defer_for_economic_review"
    else:
        recommendation = "hold_for_human_review"
    evidence_summaries = [
        _reference_evidence_summary(ref, evidence_source_mode, evidence_state_claims)
        for ref in evidence_refs
    ]
    normalized_observations = []
    for item in observations:
        amount, unit = _observation_value(item)
        normalized_observations.append({
            "metric": item.metric,
            "subject_id": item.subject_id,
                "value": str(amount),
                "unit": unit,
                "evidence_id": item.evidence_ref.evidence_id,
                "evidence_state": _safe_evidence_state(item.evidence_ref.evidence_state),
            "provenance": (
                _money_summary(item.value)["provenance"]
                if isinstance(item.value, Money)
                else _evidence_class(item.evidence_ref, evidence_source_mode)
            ),
            "uncertainty": str(item.uncertainty) if item.uncertainty is not None else (
                str(item.value.uncertainty) if isinstance(item.value, Money) and item.value.uncertainty is not None else "unknown"
            ),
        })
    economics_summary = None
    if economics is not None:
        economics_summary = {
            "service_fee": _money_summary(economics.service_fee),
            "delivery_cost": _money_summary(economics.delivery_cost),
            "tooling_cost": _money_summary(economics.tooling_cost),
            "pass_through_cost": _money_summary(economics.pass_through_cost),
            "refund_revision_reserve": _money_summary(economics.refund_revision_reserve),
            "contribution": _money_summary(economics.contribution),
            "contribution_margin": str(economics.contribution_margin) if economics.contribution_margin is not None else "unknown",
            "contribution_per_hour": _money_summary(economics.contribution_per_hour),
            "capacity_utilization": str(economics.capacity_utilization) if economics.capacity_utilization is not None else "unknown",
            "client_impact_metrics": "not_assessed",
            "evidence_state": economics.evidence_state,
        }
    promotion_summary = _promotion_summary(
        candidate_id=candidate_id,
        economics=economics,
        observations=observations,
        lane=lane,
        delivery_cost=delivery_cost,
        delivery_evidence=delivery_evidence,
        blockers=blockers,
        evidence_source_mode=evidence_source_mode,
    )
    lane_data = _lane_summary(lane)
    payload = {
        "offering_type": "service",
        "candidate_id": candidate_id,
        "workspace_id": workspace.workspace_id,
        "assessment_status": "incomplete" if blockers else "review_required",
        "recommendation": recommendation,
        "service_economics_applicability": "applicable",
        "market_access_claim": market_access_claim,
        "market_access_assessment": "not_assessed",
        "capacity_assessment": capacity_assessment,
        "unresolved_checks": unresolved_checks,
        "blockers": blockers,
        "missing_inputs": missing_inputs,
        "applicable_checks": ["service_market_evidence", "service_delivery_capacity", "service_contribution"],
        "promotion": promotion_summary,
        "market_lane": lane_data,
        "observations": normalized_observations,
        "evidence_references": evidence_summaries,
        "economics": economics_summary,
        "evidence_classes": list(dict.fromkeys(
            _evidence_class(ref, evidence_source_mode) for ref in evidence_refs
        )) or ["unknown"],
        "as_of": as_of.isoformat(),
        "read_only": True,
        "network_calls": False,
        "database_writes": False,
        "live_actions_taken": False,
    }
    export_blockers = list(blockers)
    required_evidence = ["market_access_applicability_review"]
    required_evidence.extend(missing_inputs)
    event, client_export, _ = _record_assessment(
        payload=payload,
        workspace=workspace,
        registry=registry,
        as_of=as_of,
        export_blockers=export_blockers,
        required_evidence=required_evidence,
        missing_inputs=missing_inputs,
    )
    return economics, event, client_export


def _parse_input_document(
    document: Any,
    registry: WorkspaceRegistry,
    *,
    evidence_source_mode: str,
) -> _ParsedInput:
    try:
        input_size = len(json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8"))
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise ValueError("service-market input document is not bounded JSON") from None
    if input_size > MAX_INPUT_BYTES:
        raise ValueError("service-market input size limit exceeded")
    if not isinstance(evidence_source_mode, str) or evidence_source_mode not in EVIDENCE_SOURCE_MODES:
        raise ValueError("evidence source mode is invalid")
    raw = _strict_object(document, _TOP_LEVEL_FIELDS, "input document")
    if raw["contract_id"] != INPUT_CONTRACT_ID:
        raise ValueError("service-market input contract id is unsupported")
    candidate_id = _require_identifier(raw["candidate_id"], "candidate")
    offering_type = raw["offering_type"]
    if not isinstance(offering_type, str) or offering_type not in OFFERING_TYPES:
        raise ValueError("offering type is invalid")
    workspace_id = _require_identifier(raw["workspace_id"], "workspace")
    workspace = registry.get(workspace_id)
    if workspace is None:
        raise ValueError("registered workspace is unavailable")
    as_of = _aware_datetime(raw["as_of"], "as_of")

    parsed_refs: dict[str, _ParsedEvidence] = {}

    def parse_evidence(value: Any, label: str) -> EvidenceRef:
        parsed = _parse_evidence(value, label, source_mode=evidence_source_mode)
        previous = parsed_refs.get(parsed.reference.evidence_id)
        if previous is not None and previous != parsed:
            raise ValueError("duplicate evidence identity has conflicting claims")
        parsed_refs[parsed.reference.evidence_id] = parsed
        return previous.reference if previous is not None else parsed.reference

    def parse_evidence_list(value: Any, label: str) -> tuple[EvidenceRef, ...]:
        if not isinstance(value, list) or len(value) > MAX_EVIDENCE_REFERENCES:
            raise ValueError(f"{label} evidence list is malformed or oversized")
        return tuple(parse_evidence(item, label) for item in value)

    access = _strict_object(raw["market_access"], _MARKET_ACCESS_FIELDS, "market access")
    market_access_claim = access["applicability_claim"]
    if not isinstance(market_access_claim, str) or market_access_claim not in MARKET_ACCESS_CLAIMS:
        raise ValueError("market-access applicability claim is invalid")
    if market_access_claim == "live_validated":
        market_access_claim = _SAFE_PRIVILEGED_CLAIM
    market_access_evidence = parse_evidence_list(access["evidence"], "market access")

    raw_lane = _strict_object(raw["market_lane"], _LANE_FIELDS, "market lane")
    lane_refs = parse_evidence_list(raw_lane["evidence"], "market lane")
    try:
        lane = MarketLane(
            lane_id=_require_identifier(raw_lane["lane_id"], "market lane"),
            origin=raw_lane["origin"],
            ship_from=raw_lane["ship_from"],
            warehouse=raw_lane["warehouse"],
            destination_country=raw_lane["destination_country"],
            currency=raw_lane["currency"],
            evidence_refs=lane_refs,
        )
    except (TypeError, ValueError):
        raise ValueError("market lane is malformed") from None

    raw_observations = raw["observations"]
    if not isinstance(raw_observations, list) or len(raw_observations) > MAX_MARKET_OBSERVATIONS:
        raise ValueError("service-market observation limit exceeded")
    observations: list[ServiceMarketObservation] = []
    for index, item in enumerate(raw_observations):
        observation = _strict_object(item, _OBSERVATION_FIELDS, f"observation {index}")
        reference = parse_evidence(observation["evidence"], f"observation {index}")
        metric = observation["metric"]
        uncertainty = None if observation["uncertainty"] is None else _decimal(observation["uncertainty"], "observation uncertainty")
        if uncertainty is not None and uncertainty > 1:
            raise ValueError("observation uncertainty is outside the accepted range")
        if metric == "demand":
            value: Decimal | Money = _decimal(observation["value"], "demand observation")
        elif metric == "competitor_price":
            price = _strict_object(observation["value"], frozenset({"amount", "currency"}), "competitor price")
            if price["currency"] != observation["unit"]:
                raise ValueError("competitor price currency does not match its unit")
            value = Money(
                _decimal(price["amount"], "competitor price"),
                price["currency"],
                source="bounded_market_observation",
                uncertainty=uncertainty,
                evidence_ref=reference,
                provenance={"fixture": "fixture", "manual": "manual", "unknown": "unknown", "observed": "observed", "live_validated": "unverified_claim"}[parsed_refs[reference.evidence_id].evidence_class],
                evidence_state=reference.evidence_state,
            )
        else:
            raise ValueError("unsupported service-market observation metric")
        try:
            observations.append(ServiceMarketObservation(
                metric=metric,
                subject_id=observation["subject_id"],
                value=value,
                unit=observation["unit"],
                evidence_ref=reference,
                uncertainty=uncertainty,
            ))
        except (TypeError, ValueError):
            raise ValueError(f"observation {index} is malformed") from None

    economics = _strict_object(raw["economics"], _ECONOMICS_FIELDS, "economics")
    parsed_money: dict[str, Any] = dict(economics)
    for field in ("service_fee", "labor_cost", "tooling_cost", "pass_through_cost", "refund_revision_reserve"):
        parsed_money[field], _ = _parse_money(economics[field], field, source_mode=evidence_source_mode)
        if economics[field] is not None:
            parse_evidence(economics[field]["evidence"], field)
    for amount_field, evidence_field, label in (
        ("delivery_hours", "delivery_evidence", "delivery hours"),
        ("capacity_hours", "capacity_evidence", "capacity hours"),
    ):
        amount = economics[amount_field]
        evidence = economics[evidence_field]
        if amount is not None:
            parsed_money[amount_field] = _decimal(amount, label)
        if evidence is not None:
            parsed_money[evidence_field] = parse_evidence(evidence, label)

    if len(parsed_refs) > MAX_EVIDENCE_REFERENCES:
        raise ValueError("service-market evidence reference limit exceeded")
    return _ParsedInput(
        candidate_id=candidate_id,
        offering_type=offering_type,
        workspace=workspace,
        as_of=as_of,
        market_access_claim=market_access_claim,
        market_access_evidence=market_access_evidence,
        lane=lane,
        observations=tuple(observations),
        economics=parsed_money,
        evidence_source_mode=evidence_source_mode,
        evidence_classes={key: value.evidence_class for key, value in parsed_refs.items()},
        state_claims={key: value.state_claim for key, value in parsed_refs.items()},
        unverified_privileged_claims=frozenset(
            key for key, value in parsed_refs.items() if value.unverified_privileged_claim
        ),
    )


def _safe_export_dict(
    export: ClientWorkspaceEvidenceExport,
    workspace: ClientWorkspace,
    registry: WorkspaceRegistry,
) -> dict[str, Any]:
    # Re-run the canonical TrustOS boundary immediately before serialization.
    validated = export_client_evidence(
        workspace=workspace,
        registry=registry,
        provenance=export.provenance,
        evidence_state=export.evidence_state,
        payload=export.payload,
        max_payload_bytes=export.max_payload_bytes,
    )
    return validated.to_dict()


def run_input_document(
    document: Any,
    *,
    registry: WorkspaceRegistry,
    evidence_source_mode: str = "unknown",
) -> dict[str, Any]:
    """Run the frozen offline contract through existing MarketOS authorities."""
    if not isinstance(registry, WorkspaceRegistry):
        raise ValueError("workspace registry is required")
    parsed = _parse_input_document(document, registry, evidence_source_mode=evidence_source_mode)
    evidence_refs = tuple(
        parsed.lane.evidence_refs
        + parsed.market_access_evidence
        + tuple(item.evidence_ref for item in parsed.observations)
        + tuple(
            value.evidence_ref
            for value in parsed.economics.values()
            if isinstance(value, Money) and value.evidence_ref is not None
        )
        + tuple(value for value in parsed.economics.values() if isinstance(value, EvidenceRef))
    )
    if parsed.offering_type == "service":
        economics, event, trustos_export = assess_service_market_candidate(
            candidate_id=parsed.candidate_id,
            offering_type="service",
            service_fee=parsed.economics["service_fee"],
            delivery_cost=parsed.economics["labor_cost"],
            tooling_cost=parsed.economics["tooling_cost"],
            pass_through_cost=parsed.economics["pass_through_cost"],
            refund_revision_reserve=parsed.economics["refund_revision_reserve"],
            delivery_hours=parsed.economics["delivery_hours"],
            delivery_evidence=parsed.economics["delivery_evidence"],
            capacity_hours=parsed.economics["capacity_hours"],
            capacity_evidence=parsed.economics["capacity_evidence"],
            observations=parsed.observations,
            lane=parsed.lane,
            market_access_evidence=parsed.market_access_evidence,
            market_access_claim=parsed.market_access_claim,
            evidence_source_mode=parsed.evidence_source_mode,
            evidence_classes=parsed.evidence_classes,
            evidence_state_claims=parsed.state_claims,
            unverified_privileged_claims=parsed.unverified_privileged_claims,
            workspace=parsed.workspace,
            registry=registry,
            as_of=parsed.as_of,
        )
    else:
        economics = None
        known_type = parsed.offering_type == "goods"
        blockers = [] if known_type else ["offering_type_not_assessed"]
        blockers.extend(_evidence_blockers(evidence_refs, parsed.as_of))
        blockers.extend(_observation_conflict_blockers(parsed.observations))
        for ref in evidence_refs:
            if ref.evidence_id in parsed.unverified_privileged_claims:
                blockers.append(f"unverified_privileged_evidence_claim:{ref.evidence_id}")
            elif _evidence_class(ref, parsed.evidence_source_mode) == "unknown":
                blockers.append(f"unknown_evidence_source:{ref.evidence_id}")
        if not parsed.lane.evidence_refs:
            blockers.append("missing_market_lane_evidence")
        blockers.append("market_access_not_assessed")
        if parsed.market_access_claim != "not_assessed":
            blockers.append(f"market_access_claim_requires_review:{parsed.market_access_claim}")
        blockers = list(dict.fromkeys(blockers))
        normalized_observations = []
        for item in parsed.observations:
            amount, unit = _observation_value(item)
            normalized_observations.append({
                "metric": item.metric,
                "subject_id": item.subject_id,
                "value": str(amount),
                "unit": unit,
                "evidence_id": item.evidence_ref.evidence_id,
                "evidence_state": _safe_evidence_state(item.evidence_ref.evidence_state),
            })
        evidence_integrity_issues = any(
            blocker.startswith((
                "stale_evidence:", "future_dated_evidence:", "freshness_not_assessed:",
                "conflicting_observation:", "unknown_evidence:", "unknown_evidence_source:",
                "rejected_evidence:", "unverified_privileged_evidence_claim:",
                "missing_market_lane_evidence",
            ))
            for blocker in blockers
        )
        payload = {
            "offering_type": parsed.offering_type,
            "candidate_id": parsed.candidate_id,
            "workspace_id": parsed.workspace.workspace_id,
            "assessment_status": "not_applicable" if known_type and not evidence_integrity_issues else "incomplete",
            "recommendation": "route_to_existing_goods_authority" if known_type else "defer_for_offering_classification",
            "service_economics_applicability": "not_applicable" if known_type else "not_assessed",
            "market_access_claim": parsed.market_access_claim,
            "market_access_assessment": "not_assessed",
            "blockers": list(dict.fromkeys(blockers)),
            "missing_inputs": [] if known_type else ["offering_type"],
            "market_lane": _lane_summary(parsed.lane),
            "observations": normalized_observations,
            "evidence_references": [
                _reference_evidence_summary(ref, parsed.evidence_source_mode, parsed.state_claims)
                for ref in evidence_refs
            ],
            "economics": None,
            "evidence_classes": sorted({
                _evidence_class(ref, parsed.evidence_source_mode) for ref in evidence_refs
            }) or ["unknown"],
            "as_of": parsed.as_of.isoformat(),
            "read_only": True,
            "network_calls": False,
            "database_writes": False,
            "live_actions_taken": False,
        }
        event, trustos_export, _ = _record_assessment(
            payload=payload,
            workspace=parsed.workspace,
            registry=registry,
            as_of=parsed.as_of,
            export_blockers=blockers,
            required_evidence=[] if known_type else ["offering_type_classification"],
            missing_inputs=[] if known_type else ["offering_type"],
            event_type="offering_market_assessment_recorded",
            aggregate_type="offering_market_candidate",
        )

    event_dict = event.to_dict()
    event_dict["replay_hash"] = event.replay_hash()
    replay = replay_summary([event])
    if replay["sequence_issues"] or replay["live_authority_violations"] or replay["event_count"] != 1:
        raise ValueError("service-market event replay certification failed")
    replay["canonical_event_replay_hash"] = event.replay_hash()
    result = {
        "schema": RUN_REPORT_SCHEMA,
        "execution_class": "actual_executed",
        "decision_class": "simulated_or_planned",
        "evidence_classes": event.payload["evidence_classes"],
        "derived_output": "derived" if economics is not None else "not_assessed",
        "market_access_status": event.payload["market_access_assessment"],
        "event": event_dict,
        "replay": replay,
        "trustos_export": _safe_export_dict(trustos_export, parsed.workspace, registry),
        "safety": {
            "read_only": True,
            "network_calls": False,
            "credentials_read": False,
            "provider_calls": False,
            "database_writes": False,
            "payments_or_orders": False,
            "booking_or_publishing": False,
            "live_validation": False,
        },
    }
    encoded_result = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    if len(encoded_result.encode("utf-8")) > MAX_RUN_REPORT_BYTES:
        raise ValueError("service-market run report size limit exceeded")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run bounded offline service-market evidence assessment")
    parser.add_argument("--input", required=True, help="path to a bounded MarketOS.ServiceMarketResearchInput.v1 JSON document")
    parser.add_argument("--workspace-registry", required=True, help="path to an existing read-only client workspace registry")
    args = parser.parse_args(argv)
    try:
        document = load_input_document(args.input)
        registry = WorkspaceRegistry(args.workspace_registry)
        result = run_input_document(document, registry=registry, evidence_source_mode="manual")
    except ValueError as exc:
        print(json.dumps({"schema": RUN_REPORT_SCHEMA, "error": str(exc)}, sort_keys=True, separators=(",", ":")), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False))
    return 0


__all__ = [
    "INPUT_CONTRACT_ID", "RUN_REPORT_SCHEMA", "ServiceMarketObservation",
    "assess_service_market_candidate", "load_input_document", "run_input_document", "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
