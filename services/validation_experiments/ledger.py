"""Typed, deterministic, offline validation-experiment ledger.

This module records experiment design and simulated outcomes.  It composes the
canonical synthesis, economics, CompanyOS governance, Approval Ledger, and
TrustOS isolation authorities without granting execution authority.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from backend.economics.kernel import EvidenceRef, Money, UnitEconomicsAssumptions, calculate_scenarios
from evaluation.commerce.opportunity_synthesis import build_product_opportunity_synthesis
from evaluation.companyos.approval_ledger import simulate_action
from evaluation.companyos.resource_execution_governor import ExecutionDecisionRequest, evaluate_execution_request
from evaluation.trustos.client_workspace_isolation import build_client_workspace_isolation_report
from evaluation.trustos.gate_runner import evaluate_action


class ValidationExperimentInputError(ValueError):
    """Raised when a ledger input cannot be safely represented."""


_ALLOWED_CHANNELS = frozenset({"manual_interview_simulation", "fixture_survey", "internal_replay", "offline_landing_draft"})
_RESULT_STATUSES = frozenset({"successful", "failed", "inconclusive", "invalid", "simulated", "manual", "unavailable"})
_EVIDENCE_STATES = frozenset({"unknown", "missing", "observed", "verified", "fixture", "manual_import", "simulated", "stale", "future", "conflicting", "rejected"})
_OFFERING_KINDS = frozenset({"product", "service", "hybrid", "unknown"})
_EXTERNAL_MARKERS = frozenset({"advertise", "advertising", "ad_launch", "launch_ad", "publish", "publishing", "outreach", "message", "messaging", "send", "order", "payment", "inventory", "provider_call", "customer_contact", "contact_customer", "ads_launched", "spend_executed", "publishing_performed", "outreach_sent", "orders_created", "payments_created", "provider_calls", "database_writes", "launch_authorized", "launch_authorization"})
_SECRET_MARKERS = frozenset({"api_key", "private_key", "password", "token", "access_token", "refresh_token", "authorization", "cookie", "credential", "raw_payload", "raw_html", "client_secret"})
_PILLARS = ("market", "demand", "supplier", "logistics", "economics", "marketing")


def _text(value: Any, name: str, *, required: bool = False) -> str:
    if value is None:
        if required:
            raise ValidationExperimentInputError(f"{name} is required")
        return ""
    if not isinstance(value, str):
        raise ValidationExperimentInputError(f"{name} must be text")
    value = " ".join(value.split())
    if required and not value:
        raise ValidationExperimentInputError(f"{name} is required")
    return value


def _decimal(value: Any, name: str, *, required: bool = False) -> Decimal | None:
    if value is None or value == "":
        if required:
            raise ValidationExperimentInputError(f"{name} is required")
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValidationExperimentInputError(f"{name} must be numeric") from exc
    if not result.is_finite():
        raise ValidationExperimentInputError(f"{name} must be finite")
    return result


def _positive_int(value: Any, name: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationExperimentInputError(f"{name} must be an integer") from exc
    if result <= 0:
        raise ValidationExperimentInputError(f"{name} must be positive")
    return result


def _iso(value: Any, name: str) -> datetime | None:
    text = _text(value, name)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationExperimentInputError(f"{name} must be ISO-8601") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _clean(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value.quantize(Decimal("0.01")))
    if isinstance(value, Mapping):
        return {str(key): _clean(item) for key, item in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (tuple, list)):
        return [_clean(item) for item in value]
    if isinstance(value, set):
        return [_clean(item) for item in sorted(value, key=lambda item: str(item))]
    return value


@dataclass(frozen=True)
class NormalizedOpportunityInput:
    """Typed boundary for sanitized discovery and geographic-research reports."""

    offering_kind: str
    candidate: dict[str, Any]
    candidate_evidence: tuple[dict[str, Any], ...]
    geographic_context: dict[str, Any]


def normalize_opportunity_inputs(payload: Mapping[str, Any]) -> NormalizedOpportunityInput:
    """Adapt sanitized reports without importing discovery implementations."""
    if not isinstance(payload, Mapping):
        raise ValidationExperimentInputError("opportunity input must be an object")
    _scan_unsafe(payload)
    kind = _text(payload.get("offering_kind") or "unknown", "offering_kind")
    if kind not in _OFFERING_KINDS:
        raise ValidationExperimentInputError("offering_kind must be product, service, hybrid, or unknown")
    raw_candidate = payload.get("normalized_candidate", payload.get("candidate_report"))
    if raw_candidate is None:
        candidate: dict[str, Any] = {"candidate_id": payload.get("candidate_id"), "status": "unavailable"}
    elif isinstance(raw_candidate, Mapping):
        candidate = _clean(dict(raw_candidate))
    else:
        raise ValidationExperimentInputError("normalized_candidate must be an object")
    raw_evidence = candidate.get("evidence", ())
    if not isinstance(raw_evidence, (list, tuple)):
        raise ValidationExperimentInputError("normalized candidate evidence must be a list")
    evidence: list[dict[str, Any]] = []
    for item in raw_evidence:
        if not isinstance(item, Mapping):
            raise ValidationExperimentInputError("normalized candidate evidence must be objects")
        evidence.append(_clean(dict(item)))
    raw_geography = payload.get("geographic_context", payload.get("geographic_research"))
    if raw_geography is None:
        geography: dict[str, Any] = {}
    elif isinstance(raw_geography, Mapping):
        geography = _clean(dict(raw_geography))
    else:
        raise ValidationExperimentInputError("geographic_context must be an object")
    return NormalizedOpportunityInput(kind, candidate, tuple(evidence), geography)


def _scan_unsafe(value: Any, path: str = "") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key).lower()
            if any(marker in key_text for marker in _SECRET_MARKERS):
                raise ValidationExperimentInputError(f"sensitive payload at {path}/{key}")
            if any(marker in key_text for marker in _EXTERNAL_MARKERS):
                raise ValidationExperimentInputError(f"external action payload at {path}/{key}")
            _scan_unsafe(child, f"{path}/{key}")
    elif isinstance(value, (list, tuple, set)):
        for index, child in enumerate(value):
            _scan_unsafe(child, f"{path}/{index}")
    elif isinstance(value, str):
        lower = value.lower()
        if any(marker in lower for marker in ("sk-", "bearer ", "-----begin ", "api_key=", "password=")) and (lower.startswith("sk-") or "=" in lower or lower.startswith("bearer ") or lower.startswith("-----begin ")):
            raise ValidationExperimentInputError(f"sensitive payload at {path}")


def _money(value: Any, name: str, currency: str, *, missing: list[str], explicit_zero_name: str | None = None) -> Money | None:
    """Return the field's Money value, or ``None`` when it was never supplied.

    ``None`` here is a distinct, honest "unavailable" — never a fabricated
    ``Money.zero(...)``. A caller-supplied zero (``{"amount": "0", ...}``)
    still round-trips as an explicit ``Money`` with amount ``Decimal("0")``;
    only an actually-missing field returns ``None``. This keeps "missing"
    and "observed zero" distinguishable all the way into
    ``calculate_scenarios``, which must never receive a fabricated zero in
    place of a field this function recorded as missing.
    """
    if value is None:
        missing.append(name)
        return None
    if not isinstance(value, Mapping):
        raise ValidationExperimentInputError(f"{name} must be an object")
    amount = _decimal(value.get("amount"), f"{name}.amount", required=True)
    if amount is None or amount < 0:
        raise ValidationExperimentInputError(f"{name} cannot be negative")
    item_currency = _text(value.get("currency", currency), f"{name}.currency", required=True)
    if item_currency != currency:
        raise ValidationExperimentInputError("money currencies must match")
    state = _text(value.get("state", "explicit"), f"{name}.state")
    source = "explicit" if state in {"explicit", "verified"} else "assumed"
    return Money(amount, currency, source=source, provenance=source, evidence_state="verified" if state == "verified" else "assumed")


def _state(item: Mapping[str, Any]) -> str:
    state = str(item.get("evidence_state") or item.get("state") or "unknown")
    return state if state in _EVIDENCE_STATES else "unknown"


def _evidence_summary(payload: Mapping[str, Any], as_of: datetime) -> dict[str, Any]:
    items: list[Mapping[str, Any]] = []
    for key in ("market_evidence", "supplier_evidence"):
        value = payload.get(key)
        if isinstance(value, Mapping):
            items.append(value)
    for value in payload.get("evidence_items", ()):
        if isinstance(value, Mapping):
            items.append(value)
    candidate_report = payload.get("normalized_candidate", payload.get("candidate_report"))
    if isinstance(candidate_report, Mapping):
        for value in candidate_report.get("evidence", ()):
            if isinstance(value, Mapping):
                items.append(value)
    geographic_report = payload.get("geographic_context", payload.get("geographic_research"))
    if isinstance(geographic_report, Mapping):
        for value in geographic_report.values():
            if isinstance(value, Mapping) and (value.get("evidence_state") or value.get("state")):
                items.append(value)
    states: set[str] = set()
    modes: set[str] = set()
    for item in items:
        state = _state(item)
        states.add(state)
        mode = str(item.get("evidence_mode") or "")
        if mode:
            modes.add(mode)
        captured = _iso(item.get("captured_at"), "captured_at")
        valid_until = _iso(item.get("valid_until"), "valid_until")
        if captured and captured > as_of:
            states.add("future")
        if valid_until and valid_until < as_of:
            states.add("stale")
    if not items:
        states.add("missing")
    if payload.get("conflicting_evidence") or "conflicting" in states:
        states.add("conflicting")
    mode = "fixture" if "fixture" in modes or "fixture" in states else "live" if modes and modes <= {"live_readonly", "public_live", "authenticated_live"} else "manual" if modes else "unknown"
    limitations = []
    if mode == "fixture" or "fixture" in states:
        limitations.append("fixture_evidence_not_live")
    if "stale" in states:
        limitations.append("stale_evidence")
    if "future" in states:
        limitations.append("future_evidence")
    if "conflicting" in states:
        limitations.append("conflicting_evidence")
    return {"mode": mode, "states": tuple(sorted(states)), "live_validated": mode == "live" and not states.intersection({"stale", "future", "conflicting", "missing"}), "limitations": tuple(sorted(set(limitations)))}


def _evidence_register(payload: Mapping[str, Any], as_of: datetime) -> tuple[dict[str, Any], ...]:
    """Return a typed, non-authoritative evidence register for every pillar."""
    sources = (
        ("market", "market_evidence", "market_research"),
        ("demand", "demand_evidence", "consumer_evidence"),
        ("supplier", "supplier_evidence", "supplier_research"),
        ("logistics", "logistics_evidence", "logistics_research"),
        ("marketing", "marketing_evidence", "marketing_research"),
    )
    rows: list[dict[str, Any]] = []

    def add(value: Any, pillar: str, default_class: str) -> None:
        if value is None and pillar == "demand":
            value = payload.get("consumer_evidence")
        if isinstance(value, Mapping):
            values = (value,)
        elif isinstance(value, (list, tuple)):
            values = tuple(item for item in value if isinstance(item, Mapping))
        else:
            values = ()
        for item in values:
            captured = _iso(item.get("captured_at"), "captured_at")
            valid_until = _iso(item.get("valid_until"), "valid_until")
            state = _state(item)
            if captured and captured > as_of:
                state = "future"
            elif valid_until and valid_until < as_of:
                state = "stale"
            rows.append(
                {
                    "pillar": pillar,
                    "evidence_id": str(item.get("evidence_id") or f"{pillar}-unidentified"),
                    "source": str(item.get("source") or item.get("evidence_source") or item.get("provenance") or "unspecified"),
                    "source_class": str(item.get("source_class") or item.get("evidence_class") or item.get("class") or default_class),
                    "evidence_mode": str(item.get("evidence_mode") or "unknown"),
                    "evidence_state": state,
                    "candidate_id": str(item.get("candidate_id") or payload.get("candidate_id") or "unidentified"),
                    "supplier_proof": bool(item.get("supplier_proof", False)) if pillar == "supplier" else False,
                }
            )

    for pillar, key, default_class in sources:
        add(payload.get(key), pillar, default_class)
    for item in payload.get("evidence_items", ()):
        if isinstance(item, Mapping):
            add(item, str(item.get("pillar") or "market"), "evidence_item")
    candidate_report = payload.get("normalized_candidate", payload.get("candidate_report"))
    if isinstance(candidate_report, Mapping):
        for item in candidate_report.get("evidence", ()):
            if isinstance(item, Mapping):
                add(item, str(item.get("pillar") or "market"), "candidate_report")
    geographic_report = payload.get("geographic_context", payload.get("geographic_research"))
    if isinstance(geographic_report, Mapping):
        for item in geographic_report.values():
            if isinstance(item, Mapping) and (item.get("evidence_state") or item.get("state") or item.get("evidence_id")):
                add(item, "logistics", "geographic_research")
    return tuple(sorted(rows, key=lambda row: tuple(str(row[key]) for key in ("pillar", "evidence_id", "source"))))


def _pillar_evidence(register: tuple[dict[str, Any], ...], economics: Mapping[str, Any]) -> dict[str, Any]:
    """Summarize coverage without turning attention or demand into proof."""
    result: dict[str, Any] = {}
    for pillar in _PILLARS:
        rows = [row for row in register if row["pillar"] == pillar]
        result[pillar] = {
            "status": "supplied" if rows else "missing",
            "evidence_ids": [row["evidence_id"] for row in rows],
            "source_classes": sorted({row["source_class"] for row in rows}),
            "states": sorted({row["evidence_state"] for row in rows}),
            "supplier_proof": bool(pillar == "supplier" and any(row["supplier_proof"] for row in rows)),
        }
    economics_state = "missing" if economics.get("missing_inputs") else "assumed_or_explicit"
    result["economics"] = {**result["economics"], "status": economics_state, "missing_inputs": list(economics.get("missing_inputs", ())), "source_classes": ["unit_economics_inputs"]}
    return result


def _target_offering(payload: Mapping[str, Any], candidate_id: str, offering_kind: str, candidate: Mapping[str, Any]) -> dict[str, Any]:
    supplied = payload.get("target_offering")
    if supplied is not None and not isinstance(supplied, Mapping):
        raise ValidationExperimentInputError("target_offering must be an object")
    offering = dict(supplied or {})
    offering.setdefault("candidate_id", candidate_id)
    offering.setdefault("kind", offering_kind)
    offering.setdefault("name", candidate.get("name") or candidate.get("title") or candidate_id)
    offering.setdefault("target_segment", payload.get("target_segment", ""))
    return _clean(offering)


def _decision_criteria(payload: Mapping[str, Any], thresholds: Mapping[str, Decimal]) -> dict[str, Any]:
    supplied = payload.get("decision_criteria")
    if supplied is not None and not isinstance(supplied, Mapping):
        raise ValidationExperimentInputError("decision_criteria must be an object")
    criteria = dict(supplied or {})
    criteria.setdefault("success", payload.get("success_criteria") or f"metric >= {thresholds['success_threshold']}")
    criteria.setdefault("failure", payload.get("failure_criteria") or f"metric <= {thresholds['kill_threshold']}")
    criteria.setdefault("iterate", payload.get("iterate_criteria") or f"metric between {thresholds['kill_threshold']} and {thresholds['success_threshold']}")
    return _clean(criteria)


def _assert_offline_label(value: str, name: str) -> None:
    lower = value.lower()
    if any(marker in lower for marker in _EXTERNAL_MARKERS):
        raise ValidationExperimentInputError(f"{name} cannot authorize external action")


def _pillar_reports(payload: Mapping[str, Any], evidence: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]:
    supplied = payload.get("opportunity_reports")
    if isinstance(supplied, Mapping):
        return (supplied.get("marketplace") or {}, supplied.get("supplier") or {}, supplied.get("consumer") or {})
    # Missing normalized opportunity inputs must stay missing.  In particular,
    # candidate identity alone is not evidence of demand, supply, or attention.
    return ({"evidence_mode": "missing", "candidates": []}, {"evidence_mode": "missing", "candidates": []}, {"evidence_mode": "missing", "candidates": []})


def _normalized_opportunity_pipeline(
    payload: Mapping[str, Any],
    *,
    evidence: Mapping[str, Any],
    economics: Mapping[str, Any],
    result_statuses: tuple[str, ...],
    decision: str,
    gaps: tuple[str, ...],
) -> tuple[str, dict[str, Any]]:
    normalized = normalize_opportunity_inputs(payload)
    kind = normalized.offering_kind
    candidate = normalized.candidate
    candidate_evidence = normalized.candidate_evidence

    provenance: list[str] = []
    freshness: list[str] = []
    conflicts: list[str] = []
    for item in candidate_evidence:
        if not isinstance(item, Mapping):
            raise ValidationExperimentInputError("normalized candidate evidence must be objects")
        if item.get("provenance"):
            provenance.append(str(item["provenance"]))
        state = str(item.get("state") or item.get("evidence_state") or "unknown")
        if state in {"stale", "future"}:
            freshness.append(state)
        if bool(item.get("conflicting")) or state == "conflicting":
            conflicts.append(str(item.get("evidence_id") or "candidate_evidence"))

    geography = normalized.geographic_context
    geography_provenance: list[str] = []
    geography_states: set[str] = set()
    for item in geography.values():
        if isinstance(item, Mapping):
            if item.get("provenance"):
                geography_provenance.append(str(item["provenance"]))
            state = item.get("state") or item.get("evidence_state")
            if state:
                geography_states.add(str(state))
    geography_kind = _text(geography.get("geography_kind") or "unknown", "geography_kind")
    if geography_kind not in {"known", "unknown"}:
        raise ValidationExperimentInputError("geography_kind must be known or unknown")
    uncertainty: set[str] = set()
    if geography_kind == "unknown":
        uncertainty.add("geography_unknown")
    for field_name in ("trade_flow", "freight_duty", "returns_lead_time", "service_capacity", "regulatory"):
        item = geography.get(field_name)
        if item is None:
            if geography_kind == "known" and field_name in {"trade_flow", "freight_duty"}:
                uncertainty.add(f"{field_name}_unknown")
            continue
        if not isinstance(item, Mapping):
            raise ValidationExperimentInputError(f"geographic_context.{field_name} must be an object")
        state = str(item.get("state") or item.get("evidence_state") or "unknown")
        if state in {"unknown", "missing", "stale", "future", "conflicting"}:
            uncertainty.add(f"{field_name}_{state}")
        if item.get("uncertainty"):
            uncertainty.add(str(item["uncertainty"]))

    cheapest_test = {
        "method": _text(payload.get("test_method"), "test_method", required=True),
        "channel": _text(payload.get("permitted_channel"), "permitted_channel", required=True),
        "sample_target": int(payload["sample_target"]),
        "budget": payload.get("assumed_budget") or {"state": "missing", "amount": "unknown"},
        "falsifies": payload.get("kill_threshold"),
        "read_only": True,
    }
    if "reachable_buyer" in gaps or "reachable_buyer" in payload and not payload.get("reachable_buyer"):
        cheapest_test["rationale"] = "Test reachable-buyer access before interpreting demand strength."
    elif "product_cost" in economics.get("missing_inputs", ()):
        cheapest_test["rationale"] = "Resolve missing product cost before trusting unit economics."
    else:
        cheapest_test["rationale"] = "Use the smallest offline sample that can cross the stated threshold."

    next_action = {
        "kill_negative_unit_economics": "resolve_unit_economics",
        "blocked_missing_budget": "define_experiment_budget",
        "hold_unreachable_buyer": "validate_reachable_buyer",
        "blocked_missing_economics": "resolve_unit_economics",
        "blocked_supplier_evidence": "resolve_supplier_evidence",
        "blocked_evidence_integrity": "repair_evidence_provenance",
        "reject_invalid_result": "repair_result_provenance",
        "kill_failed_result": "revise_hypothesis_or_stop",
        "advance_to_human_review": "review_simulated_result",
        "iterate_inconclusive_result": "run_cheapest_falsification_test",
    }.get(decision, "human_review")
    pipeline = {
        "contract": "MarketOS.ValidationOpportunityPipeline.v1",
        "economic_mode": kind,
        "candidate": _clean(candidate) if isinstance(candidate, Mapping) else {"candidate_id": payload.get("candidate_id"), "status": "unavailable"},
        "evidence": {"mode": evidence["mode"], "provenance": list(sorted(set(provenance))), "freshness": list(sorted(set(freshness))), "conflicts": list(sorted(set(conflicts)))},
        "geography": {"kind": geography_kind, "origin": geography.get("origin", "unknown"), "destination": geography.get("destination", "unknown"), "uncertainty": list(sorted(uncertainty)), "provenance": list(sorted(set(geography_provenance))), "states": list(sorted(geography_states))},
        "hypothesis": payload["hypothesis"],
        "cheapest_falsification_test": cheapest_test,
        "thresholds": {"success": payload["success_threshold"], "iterate": payload["iterate_threshold"], "kill": payload["kill_threshold"]},
        "result_classification": tuple(sorted(result_statuses)),
        "decision": decision,
        "next_action": next_action,
        "client_safe": True,
        "read_only": True,
    }
    return kind, pipeline


def _canonical_fingerprint(data: Mapping[str, Any]) -> str:
    body = dict(data)
    body.pop("fingerprint", None)
    encoded = json.dumps(_clean(body), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ValidationExperimentLedger:
    workspace_id: str
    candidate_id: str
    hypothesis: str
    target_segment: str
    permitted_channel: str
    test_method: str
    evidence_required: tuple[str, ...]
    assumed_budget: dict[str, Any]
    sample_target: int
    success_threshold: str
    kill_threshold: str
    iterate_threshold: str
    measurement_method: str
    approval_state: str
    result_statuses: tuple[str, ...]
    decision: str
    blockers: tuple[str, ...]
    evidence_gaps: tuple[str, ...]
    limitations: tuple[str, ...]
    provenance: str
    evidence_summary: dict[str, Any]
    economics: dict[str, Any]
    opportunity_summary: dict[str, Any]
    approval_simulation: dict[str, Any]
    governor_decision: dict[str, Any]
    trustos_decision: dict[str, Any]
    workspace_summary: dict[str, Any]
    safety_summary: dict[str, Any]
    generated_at: str = "offline-deterministic"
    fingerprint: str = ""
    offering_kind: str = "unknown"
    validation_pipeline: dict[str, Any] = field(default_factory=dict)
    target_offering: dict[str, Any] = field(default_factory=dict)
    expected_decision: str = "human_review"
    decision_criteria: dict[str, Any] = field(default_factory=dict)
    evidence_register: tuple[dict[str, Any], ...] = ()
    pillar_evidence: dict[str, Any] = field(default_factory=dict)
    human_review: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = _clean({key: value for key, value in self.__dict__.items() if key != "fingerprint"})
        data["fingerprint"] = self.fingerprint or _canonical_fingerprint(data)
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    def to_markdown(self) -> str:
        pipeline = self.validation_pipeline
        return "\n".join(
            (
                "## Validation experiment",
                "",
                f"- Candidate: {self.candidate_id}",
                f"- Target offering: {self.target_offering.get('name', self.candidate_id)} ({self.offering_kind})",
                f"- Offering kind: {self.offering_kind}",
                f"- Expected decision: {self.expected_decision}",
                f"- Decision: {self.decision}",
                f"- Next action: {pipeline.get('next_action', 'human_review')}",
                f"- Cheapest falsification test: {pipeline.get('cheapest_falsification_test', {}).get('method', self.test_method)}",
                "- Mode: offline, read-only, simulation-only",
                "- External actions: blocked; this is planning output only.",
            )
        )


def build_validation_experiment_ledger(payload: Mapping[str, Any], *, expected_workspace_id: str | None = None, as_of: str = "2026-09-22T00:00:00Z") -> ValidationExperimentLedger:
    if not isinstance(payload, Mapping):
        raise ValidationExperimentInputError("payload must be an object")
    _scan_unsafe(payload)
    workspace_id = _text(payload.get("workspace_id"), "workspace_id", required=True)
    expected = expected_workspace_id or _text(payload.get("expected_workspace_id"), "expected_workspace_id")
    if expected and workspace_id != expected:
        raise ValidationExperimentInputError("workspace identity mismatch")
    channel = _text(payload.get("permitted_channel"), "permitted_channel", required=True)
    if channel not in _ALLOWED_CHANNELS:
        raise ValidationExperimentInputError("external action channel is not permitted")
    as_of_dt = _iso(as_of, "as_of") or datetime(2026, 9, 22, tzinfo=timezone.utc)
    candidate_id = _text(payload.get("candidate_id"), "candidate_id", required=True)
    hypothesis = _text(payload.get("hypothesis"), "hypothesis", required=True)
    segment = _text(payload.get("target_segment"), "target_segment", required=True)
    test_method = _text(payload.get("test_method"), "test_method", required=True)
    _assert_offline_label(test_method, "test_method")
    measurement = _text(payload.get("measurement_method"), "measurement_method", required=True)
    evidence_required = tuple(sorted(str(item) for item in payload.get("evidence_required", ()) if str(item)))
    sample_target = _positive_int(payload.get("sample_target"), "sample_target")
    thresholds = {name: _decimal(payload.get(name), name, required=True) for name in ("success_threshold", "kill_threshold", "iterate_threshold")}
    if any(value is None or value < 0 or value > 1 for value in thresholds.values()):
        raise ValidationExperimentInputError("thresholds must be between zero and one")
    if not thresholds["kill_threshold"] <= thresholds["iterate_threshold"] <= thresholds["success_threshold"]:
        raise ValidationExperimentInputError("thresholds must be ordered kill, iterate, success")
    currency = str((payload.get("price") or {}).get("currency", "USD")) if isinstance(payload.get("price"), Mapping) else "USD"
    missing_inputs: list[str] = []
    price = _money(payload.get("price"), "price", currency, missing=missing_inputs)
    product_cost = _money(payload.get("product_cost"), "product_cost", currency, missing=missing_inputs)
    cac = _money(payload.get("cac"), "cac", currency, missing=missing_inputs)
    budget_value = payload.get("assumed_budget")
    if budget_value is None:
        budget = {"state": "missing", "amount": "unknown", "currency": currency}
    else:
        budget_money = _money(budget_value, "assumed_budget", currency, missing=[])
        budget = {"state": "assumed", **budget_money.to_dict()}
    refs = (EvidenceRef(evidence_id=f"validation-{candidate_id}", source_type="offline_validation", evidence_state="simulated", extraction_method="manual_fixture"),)
    # calculate_scenarios (backend.economics.kernel, the sole economics authority)
    # requires real Money for price and product_cost; it has no "missing" input
    # concept for either. A missing price or product_cost must never be
    # papered over with a fabricated Money.zero(...) just to satisfy that
    # signature -- doing so would let an unavailable field enter the real
    # calculation indistinguishably from an observed zero. So scenarios are
    # only ever computed when both are actually present; otherwise the
    # economics section stays explicitly unavailable, and missing_inputs
    # (already recorded by `_money`) is what downstream blocking depends on.
    # cac has a genuine "missing" representation already: UnitEconomicsAssumptions
    # accepts cac=None, so a missing cac is passed through as None rather than
    # a fabricated zero.
    if price is not None and product_cost is not None:
        economics_results = calculate_scenarios(price, product_cost, assumptions=UnitEconomicsAssumptions(cac=cac, evidence_refs=refs))
        scenarios = {name: item.to_dict() for name, item in economics_results.items()}
        base_after = economics_results["base"].contribution_after_cac.amount
        economics_status = "computed"
    else:
        economics_results = None
        scenarios = {}
        base_after = None
        economics_status = "unavailable"
    economics = {"scenarios": scenarios, "status": economics_status, "base_cost_state": "missing" if "product_cost" in missing_inputs else "explicit_zero" if product_cost.amount == 0 else "explicit", "missing_inputs": tuple(missing_inputs)}
    evidence = _evidence_summary(payload, as_of_dt)
    market, supplier, consumer = _pillar_reports(payload, evidence)
    opportunity = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    opportunity["scoring_authority"] = "evaluation.commerce.opportunity_synthesis.build_product_opportunity_synthesis"
    result_rows = payload.get("result_statuses")
    if result_rows is None:
        result_rows = [((payload.get("result") or {}).get("status") or "simulated")]
    if not isinstance(result_rows, (list, tuple)) or not result_rows:
        raise ValidationExperimentInputError("result status must be a list")
    result_statuses = tuple(str(row) for row in result_rows)
    if not result_statuses or any(status not in _RESULT_STATUSES for status in result_statuses):
        raise ValidationExperimentInputError("result status is invalid")
    economics_blocked = bool({"price", "product_cost", "cac"}.intersection(missing_inputs))
    blockers: list[str] = []
    gaps: list[str] = []
    if "manual" in result_statuses or "unavailable" in result_statuses:
        gaps.append("manual_or_unavailable_result")
    if not payload.get("reachable_buyer", False):
        blockers.append("reachable_buyer")
    if "supplier_evidence" in evidence_required and not isinstance(payload.get("supplier_evidence"), Mapping):
        gaps.append("supplier_evidence")
        blockers.append("supplier_evidence")
    if "experiment_budget" in evidence_required and budget_value is None:
        blockers.append("experiment_budget")
    if budget_value is None:
        blockers.append("experiment_budget")
    if missing_inputs:
        gaps.extend(missing_inputs)
    if economics_blocked:
        blockers.append("missing_economics")
    if any(item in evidence["states"] for item in ("stale", "future", "conflicting")):
        gaps.extend(item for item in ("stale_evidence", "future_evidence", "conflicting_evidence") if item in evidence["states"])
        blockers.append("evidence_integrity")
    if "fixture_evidence_not_live" in evidence["limitations"]:
        gaps.append("fixture_evidence_not_live")
    if not payload.get("opportunity_reports") and not payload.get("normalized_candidate") and not any(payload.get(key) for key in ("market_evidence", "supplier_evidence")):
        gaps.append("opportunity_evidence")
    budget_amount = float(budget_value.get("amount", 0)) if isinstance(budget_value, Mapping) else 0.0
    approval_sim = simulate_action("launch_ad", requested_budget=budget_amount, generated_at="offline-deterministic").to_dict()
    request = ExecutionDecisionRequest(request_id=f"validation-{candidate_id}", action_type="launch_ad_experiment", domain="ads_content", owner_department="validation", workspace_id=workspace_id, requested_amount=budget_amount, hypothesis=hypothesis, success_metric=measurement, kill_threshold=float(thresholds["kill_threshold"]), scale_threshold=float(thresholds["success_threshold"]), sample_size_target=sample_target, approval_state="approved" if payload.get("approval_state") == "approved" else "not_requested", trustos_decision="hard_block", workspace_decision="allow")
    governor = evaluate_execution_request(request).to_dict()
    trustos = evaluate_action("launch_ad", generated_at="offline-deterministic").to_dict()
    if "stale_evidence" in gaps or "future_evidence" in gaps or "conflicting_evidence" in gaps:
        blockers.append("evidence_integrity")
    if "fixture_evidence_not_live" in gaps:
        blockers.append("fixture_evidence_not_live")
    if any(state in evidence["states"] for state in ("invalid", "rejected")):
        blockers.append("rejected_evidence")
    blockers = list(dict.fromkeys(blockers))
    if "experiment_budget" in blockers:
        decision = "blocked_missing_budget"
    elif economics_blocked:
        decision = "blocked_missing_economics"
    elif "supplier_evidence" in blockers:
        decision = "blocked_supplier_evidence"
    elif base_after is not None and base_after < 0:
        decision = "kill_negative_unit_economics"
    elif "reachable_buyer" in blockers:
        decision = "hold_unreachable_buyer"
    elif "evidence_integrity" in blockers or "fixture_evidence_not_live" in blockers or "rejected_evidence" in blockers:
        decision = "blocked_evidence_integrity"
    elif any(status == "invalid" for status in result_statuses):
        decision = "reject_invalid_result"
    elif any(status == "successful" for status in result_statuses) and not {"manual", "unavailable"}.intersection(result_statuses):
        decision = "advance_to_human_review"
    elif any(status == "failed" for status in result_statuses):
        decision = "kill_failed_result"
    else:
        decision = "iterate_inconclusive_result"
    workspace = build_client_workspace_isolation_report(workspace_type="client_growth_workspace", payload={"workspace_id": workspace_id, "status": "client_safe", "blockers": tuple(blockers), "evidence_required": tuple(gaps), "approvals_required": ("human_review",), "next_actions": (decision,)}).to_dict()
    approval_state = "pending_review" if decision == "advance_to_human_review" else "blocked_by_policy" if blockers or (base_after is not None and base_after < 0) else "draft"
    limitations = tuple(sorted(set(evidence["limitations"] + (("external_execution_blocked",) if True else ()))))
    safety = {"read_only": True, "network_calls": False, "ads_launched": False, "spend_executed": False, "publishing_performed": False, "outreach_sent": False, "orders_created": False, "payments_created": False, "provider_calls": False, "customer_contact": False, "database_writes": False}
    offering_kind, validation_pipeline = _normalized_opportunity_pipeline(payload, evidence=evidence, economics=economics, result_statuses=result_statuses, decision=decision, gaps=tuple(gaps))
    candidate = validation_pipeline.get("candidate", {}) if isinstance(validation_pipeline.get("candidate"), Mapping) else {}
    target_offering = _target_offering(payload, candidate_id, offering_kind, candidate)
    expected_decision = _text(payload.get("expected_decision") or "human_review", "expected_decision", required=True)
    _assert_offline_label(expected_decision, "expected_decision")
    decision_criteria = _decision_criteria(payload, thresholds)
    evidence_register = _evidence_register(payload, as_of_dt)
    pillar_evidence = _pillar_evidence(evidence_register, economics)
    human_review = {
        "required": True,
        "status": "pending" if decision == "advance_to_human_review" else "blocked_or_not_ready",
        "approval_state": approval_state,
        "reviewer": _text(payload.get("reviewer"), "reviewer"),
        "launch_authority": False,
    }
    validation_pipeline["target_offering"] = target_offering
    validation_pipeline["expected_decision"] = expected_decision
    validation_pipeline["decision_criteria"] = decision_criteria
    validation_pipeline["pillars"] = pillar_evidence
    validation_pipeline["human_review"] = human_review
    provisional = ValidationExperimentLedger(workspace_id, candidate_id, hypothesis, segment, channel, test_method, evidence_required, budget, sample_target, str(thresholds["success_threshold"]), str(thresholds["kill_threshold"]), str(thresholds["iterate_threshold"]), measurement, approval_state, result_statuses, decision, tuple(sorted(set(blockers))), tuple(sorted(set(gaps))), limitations, _text(payload.get("provenance"), "provenance", required=True), evidence, economics, {"candidate_id": opportunity.get("top_candidate_id"), "scoring_authority": "evaluation.commerce.opportunity_synthesis.build_product_opportunity_synthesis", "report": opportunity}, approval_sim, governor, trustos, {"workspace_id": workspace_id, "client_safe": True, "safety_summary": workspace.get("safety_summary", {})}, safety, offering_kind=offering_kind, validation_pipeline=validation_pipeline, target_offering=target_offering, expected_decision=expected_decision, decision_criteria=decision_criteria, evidence_register=evidence_register, pillar_evidence=pillar_evidence, human_review=human_review)
    return ValidationExperimentLedger(**{**provisional.__dict__, "fingerprint": _canonical_fingerprint(provisional.to_dict())})
