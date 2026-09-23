"""Offline, product-agnostic opportunity discovery.

This module is an adapter around existing MarketOS authorities.  It owns the
input contract, fatal evidence gates, and deterministic report projection; it
does not replace opportunity synthesis, economics, Governor, or TrustOS.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

from backend.economics.kernel import (
    EVIDENCE_STATES,
    EvidenceRef,
    EconomicsError,
    MarketLane,
    Money,
    UnitEconomicsAssumptions,
    calculate_scenarios,
    calculate_service_economics,
)
from evaluation.companyos.resource_execution_governor import (
    ExecutionDecisionRequest,
    evaluate_execution_request,
)
from evaluation.commerce.opportunity_synthesis import build_product_opportunity_synthesis
from evaluation.trustos.client_workspace_isolation import export_client_evidence


DISCOVERY_MODES = ("discover", "evaluate", "compare", "validate", "review-results")
OFFERING_KINDS = ("product", "service", "hybrid", "unknown")
EVIDENCE_STATUSES = (
    "observed_fact",
    "derived_calculation",
    "inference",
    "hypothesis",
    "assumption",
    "unknown",
    "unavailable",
)
EVIDENCE_CLASSES = (
    "fixture",
    "manual",
    "observed",
    "derived",
    "simulated",
    "unknown",
    "unavailable",
    "live_validated",
)
MAX_INPUT_BYTES = 64 * 1024
MAX_CANDIDATES = 50
MAX_EVIDENCE = 250
MAX_DEPTH = 12
MAX_NODES = 2_000
MAX_OUTPUT_BYTES = 128 * 1024

_SECRET_KEY = re.compile(
    r"(?:api[_-]?key|access[_-]?token|auth(?:orization)?|client[_-]?secret|credential|cookie|password|private[_-]?key|secret|token)",
    re.IGNORECASE,
)
_FORBIDDEN_KEY = re.compile(r"(?:raw[_-]?payload|html|prompt|formula|source[_-]?code|stack[_-]?trace)", re.IGNORECASE)
_FORBIDDEN_VALUE = re.compile(r"(?:BEGIN [A-Z ]+PRIVATE KEY|<\s*(?:script|html)|ignore (?:all|previous)|system prompt)", re.IGNORECASE)
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")


class OpportunityDiscoveryError(ValueError):
    """Stable input or contract error without reflecting unsafe input."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _decimal(value: Any, field_name: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise OpportunityDiscoveryError(f"invalid_{field_name}")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise OpportunityDiscoveryError(f"invalid_{field_name}") from None
    if not result.is_finite():
        raise OpportunityDiscoveryError(f"invalid_{field_name}")
    return result


def _json_safe(value: Any, *, depth: int = 0, nodes: list[int] | None = None) -> Any:
    """Copy a bounded JSON-like value while rejecting secret-shaped content."""
    nodes = nodes if nodes is not None else [0]
    nodes[0] += 1
    if nodes[0] > MAX_NODES or depth > MAX_DEPTH:
        raise OpportunityDiscoveryError("input_bounds_exceeded")
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, child in value.items():
            if not isinstance(raw_key, str):
                raise OpportunityDiscoveryError("invalid_field_name")
            if _SECRET_KEY.search(raw_key) or _FORBIDDEN_KEY.search(raw_key):
                raise OpportunityDiscoveryError("sensitive_field_rejected")
            result[raw_key] = _json_safe(child, depth=depth + 1, nodes=nodes)
        return result
    if isinstance(value, (list, tuple)):
        return [_json_safe(child, depth=depth + 1, nodes=nodes) for child in value]
    if isinstance(value, str):
        if len(value.encode("utf-8")) > 4_096 or _FORBIDDEN_VALUE.search(value):
            raise OpportunityDiscoveryError("sensitive_value_rejected")
        return value
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise OpportunityDiscoveryError("invalid_numeric_value")
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise OpportunityDiscoveryError("invalid_numeric_value")
        return value
    raise OpportunityDiscoveryError("unsupported_input_value")


def _canonical(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        return "{" + ",".join(json.dumps(str(key)) + ":" + _canonical(value[key]) for key in sorted(value, key=str)) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_canonical(item) for item in value) + "]"
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), default=str)


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _ensure_id(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise OpportunityDiscoveryError(f"invalid_{field_name}")
    return value


def _text(value: Any, field_name: str, *, default: str = "") -> str:
    if value is None:
        return default
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise OpportunityDiscoveryError(f"invalid_{field_name}")
    return value.strip()


def _source_class(value: Any) -> str:
    return value if value in EVIDENCE_CLASSES else "unknown"


def _status(value: Any) -> str:
    return value if value in EVIDENCE_STATUSES else "unknown"


def _kernel_state(evidence_class: str, status: str) -> str:
    if status == "derived_calculation" or evidence_class == "derived":
        return "derived"
    if evidence_class == "fixture":
        return "fixture"
    if evidence_class == "simulated":
        return "simulated"
    if evidence_class == "observed" and status == "observed_fact":
        return "observed"
    if evidence_class == "manual":
        return "assumed"
    return "unknown"


@dataclass(frozen=True)
class OpportunityEvidence:
    evidence_id: str
    area: str
    status: str
    evidence_class: str
    source_type: str = "unknown"
    source_ref: str = ""
    freshness: str = "unknown"
    conflicting: bool = False
    value: Any = None
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "area": self.area,
            "status": self.status,
            "evidence_class": self.evidence_class,
            "source_type": self.source_type,
            "source_ref": self.source_ref,
            "freshness": self.freshness,
            "conflicting": self.conflicting,
            "value": self.value,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class ValidationExperiment:
    experiment_id: str
    question: str
    method: str
    required_evidence: tuple[str, ...]
    success_thresholds: Mapping[str, Any]
    kill_thresholds: Mapping[str, Any]
    iterate_rule: str
    estimated_cost: Mapping[str, Any]
    external_action_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "question": self.question,
            "method": self.method,
            "required_evidence": list(self.required_evidence),
            "success_thresholds": dict(self.success_thresholds),
            "kill_thresholds": dict(self.kill_thresholds),
            "iterate_rule": self.iterate_rule,
            "estimated_cost": dict(self.estimated_cost),
            "external_action_allowed": False,
        }


@dataclass(frozen=True)
class OpportunityCandidate:
    candidate_id: str
    name: str
    offering_kind: str
    category: str
    geography: Mapping[str, Any]
    evidence: tuple[OpportunityEvidence, ...]
    economics: Mapping[str, Any]
    reports: Mapping[str, Any]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "name": self.name,
            "offering_kind": self.offering_kind,
            "category": self.category,
            "geography": dict(self.geography),
            "evidence": [item.to_dict() for item in self.evidence],
            "economics": dict(self.economics),
            "reports": dict(self.reports),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class OpportunityDecision:
    candidate_id: str
    recommendation: str
    readiness: str
    fatal_gates: tuple[str, ...]
    blockers: tuple[str, ...]
    evidence_gaps: tuple[str, ...]
    evidence_classes: tuple[str, ...]
    metrics: Mapping[str, Any]
    scenarios: Mapping[str, Any]
    sensitivity_drivers: tuple[str, ...]
    experiment: ValidationExperiment
    synthesis: Mapping[str, Any]
    governor: Mapping[str, Any]
    trustos_export: Mapping[str, Any]
    review_results: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "recommendation": self.recommendation,
            "readiness": self.readiness,
            "fatal_gates": list(self.fatal_gates),
            "blockers": list(self.blockers),
            "evidence_gaps": list(self.evidence_gaps),
            "evidence_classes": list(self.evidence_classes),
            "metrics": dict(self.metrics),
            "scenarios": dict(self.scenarios),
            "sensitivity_drivers": list(self.sensitivity_drivers),
            "experiment": self.experiment.to_dict(),
            "synthesis": dict(self.synthesis),
            "governor": dict(self.governor),
            "trustos_export": dict(self.trustos_export),
            "review_results": dict(self.review_results),
        }


@dataclass(frozen=True)
class DiscoveryRun:
    run_version: str
    mode: str
    status: str
    execution_classification: str
    candidates: tuple[OpportunityCandidate, ...]
    decisions: tuple[OpportunityDecision, ...]
    ranked_candidate_ids: tuple[str, ...]
    blockers: tuple[str, ...]
    next_best_action: str
    safety: Mapping[str, Any]
    fingerprint: str = ""

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, Any]:
        result = {
            "run_version": self.run_version,
            "mode": self.mode,
            "status": self.status,
            "execution_classification": self.execution_classification,
            "candidates": [item.to_dict() for item in self.candidates],
            "decisions": [item.to_dict() for item in self.decisions],
            "ranked_candidate_ids": list(self.ranked_candidate_ids),
            "blockers": list(self.blockers),
            "next_best_action": self.next_best_action,
            "safety": dict(self.safety),
        }
        if include_fingerprint:
            result["fingerprint"] = self.fingerprint
        return result


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise OpportunityDiscoveryError("duplicate_input_key")
        result[key] = value
    return result


def load_payload(raw: str | bytes) -> Mapping[str, Any]:
    """Load one bounded JSON payload and reject duplicate keys."""
    data = raw.encode("utf-8") if isinstance(raw, str) else raw
    if not isinstance(data, bytes) or len(data) > MAX_INPUT_BYTES:
        raise OpportunityDiscoveryError("input_size_exceeded")
    try:
        parsed = json.loads(data.decode("utf-8"), object_pairs_hook=_object_pairs)
    except OpportunityDiscoveryError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise OpportunityDiscoveryError("malformed_json") from None
    if not isinstance(parsed, Mapping):
        raise OpportunityDiscoveryError("root_must_be_object")
    return _json_safe(parsed)


def _normalize_evidence(raw: Any, *, default_area: str) -> tuple[OpportunityEvidence, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or len(raw) > MAX_EVIDENCE:
        raise OpportunityDiscoveryError("invalid_evidence_collection")
    result: list[OpportunityEvidence] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise OpportunityDiscoveryError("invalid_evidence_item")
        evidence_id = _ensure_id(item.get("evidence_id", f"evidence-{len(result) + 1}"), "evidence_id")
        area = _text(item.get("area"), "evidence_area", default=default_area)
        source_type = _text(item.get("source_type"), "source_type", default="unknown")
        requested_class = _source_class(item.get("evidence_class", item.get("source", "unknown")))
        requested_status = _status(item.get("status", "unknown"))
        notes: list[str] = []
        evidence_class = requested_class
        status = requested_status
        if requested_class == "live_validated":
            evidence_class = "unavailable"
            status = "unavailable"
            notes.append("live_validation_not_available_in_offline_engine")
        if source_type == "supplier_claim" and status == "observed_fact":
            status = "hypothesis"
            notes.append("supplier_claim_is_not_independent_verification")
        freshness = item.get("freshness", "unknown")
        if freshness not in {"current", "stale", "future", "unknown"}:
            freshness = "unknown"
            notes.append("freshness_unrecognized")
        result.append(OpportunityEvidence(evidence_id, area, status, evidence_class, source_type, _text(item.get("source_ref"), "source_ref"), freshness, bool(item.get("conflicting", False)), item.get("value"), tuple(notes)))
    return tuple(sorted(result, key=lambda item: item.evidence_id))


def _normalize_candidate(raw: Any, index: int) -> OpportunityCandidate:
    if not isinstance(raw, Mapping):
        raise OpportunityDiscoveryError("invalid_candidate")
    candidate_id = _ensure_id(raw.get("candidate_id", f"candidate-{index + 1}"), "candidate_id")
    name = _text(raw.get("name", raw.get("title")), "candidate_name")
    offering_kind = raw.get("offering_kind", "unknown")
    if offering_kind not in OFFERING_KINDS:
        raise OpportunityDiscoveryError("invalid_offering_kind")
    category = _text(raw.get("category"), "category", default="unknown")
    geography = raw.get("geography", {})
    if not isinstance(geography, Mapping):
        raise OpportunityDiscoveryError("invalid_geography")
    reports = raw.get("reports", {})
    if not isinstance(reports, Mapping):
        raise OpportunityDiscoveryError("invalid_reports")
    economics = raw.get("economics", {})
    if not isinstance(economics, Mapping):
        raise OpportunityDiscoveryError("invalid_economics")
    return OpportunityCandidate(
        candidate_id,
        name,
        offering_kind,
        category,
        dict(sorted(geography.items(), key=lambda item: str(item[0]))),
        _normalize_evidence(raw.get("evidence", ()), default_area="candidate"),
        dict(economics),
        dict(reports),
        dict(raw.get("metadata", {})) if isinstance(raw.get("metadata", {}), Mapping) else {},
    )


def _evidence_gaps(candidate: OpportunityCandidate) -> tuple[list[str], list[str], list[str]]:
    gaps: set[str] = set()
    blockers: set[str] = set()
    classes: set[str] = set()
    for item in candidate.evidence:
        classes.add(item.evidence_class)
        if item.status in {"unknown", "unavailable"} or item.freshness in {"stale", "future", "unknown"}:
            gaps.add(f"{item.area}_evidence_{item.status if item.status in {'unknown', 'unavailable'} else item.freshness}")
        if item.freshness == "future":
            blockers.add("future_dated_evidence")
        if item.conflicting:
            blockers.add(f"conflicting_{item.area}_evidence")
        if item.source_type == "supplier_claim":
            blockers.add("supplier_claim_not_verification")
        blockers.update(item.notes)
    return sorted(gaps), sorted(blockers), sorted(classes)


def _evidence_ref(candidate: OpportunityCandidate, area: str) -> EvidenceRef | None:
    item = next((item for item in candidate.evidence if item.area == area), None)
    if item is None:
        return None
    state = _kernel_state(item.evidence_class, item.status)
    if state not in EVIDENCE_STATES:
        state = "unknown"
    return EvidenceRef(item.evidence_id, item.source_type, document_ref=item.source_ref, extraction_method="offline_input", evidence_state=state)


def _money(value: Any, *, currency: str, candidate: OpportunityCandidate, area: str, field_name: str) -> Money:
    if isinstance(value, Mapping):
        amount = value.get("amount")
        money_currency = value.get("currency", currency)
        source = value.get("source", "input")
        provenance = value.get("provenance", "assumed")
        evidence_state = value.get("evidence_state", _kernel_state("unknown", "unknown"))
        tax_inclusion_state = value.get("tax_inclusion_state", "unknown")
        if evidence_state not in EVIDENCE_STATES:
            evidence_state = "unknown"
    else:
        amount = value
        money_currency = currency
        source = "input"
        provenance = "assumed"
        evidence_state = "assumed"
        tax_inclusion_state = "unknown"
    if amount is None:
        raise OpportunityDiscoveryError(f"missing_{field_name}")
    try:
        return Money(amount, str(money_currency), source=str(source), provenance=str(provenance), evidence_state=evidence_state, evidence_ref=_evidence_ref(candidate, area), tax_inclusion_state=str(tax_inclusion_state))
    except EconomicsError as exc:
        raise OpportunityDiscoveryError(f"invalid_{field_name}") from exc


def _lane(candidate: OpportunityCandidate, currency: str) -> MarketLane | None:
    raw = candidate.geography
    if not raw:
        return None
    try:
        return MarketLane(
            lane_id=_ensure_id(raw.get("lane_id", f"lane-{candidate.candidate_id}"), "lane_id"),
            origin=_text(raw.get("origin"), "origin", default="unknown"),
            ship_from=_text(raw.get("ship_from"), "ship_from", default="unknown"),
            warehouse=_text(raw.get("warehouse"), "warehouse", default="unknown"),
            destination_country=_text(raw.get("destination_country"), "destination_country", default="unknown"),
            destination_region=_text(raw.get("destination_region"), "destination_region", default=""),
            currency=currency,
            tax_rate=raw.get("tax_rate", 0),
            duty_rate=raw.get("duty_rate", 0),
            evidence_refs=tuple(ref for ref in (_evidence_ref(candidate, "geography"),) if ref),
        )
    except (EconomicsError, OpportunityDiscoveryError) as exc:
        raise OpportunityDiscoveryError("invalid_market_lane") from exc


def _unit_scenarios(candidate: OpportunityCandidate) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    raw = candidate.economics
    currency = str(raw.get("currency", candidate.geography.get("currency", "USD"))).upper()
    missing: list[str] = []
    price_value = raw.get("price")
    cost_value = raw.get("product_cost")
    if price_value is None:
        missing.append("price")
    if cost_value is None:
        missing.append("product_cost")
    required = raw.get("required_inputs", ("shipping",))
    if not isinstance(required, (list, tuple)):
        raise OpportunityDiscoveryError("invalid_required_inputs")
    assumptions_raw = raw.get("assumptions", {})
    if not isinstance(assumptions_raw, Mapping):
        raise OpportunityDiscoveryError("invalid_economics_assumptions")
    if "shipping" in required and not any(key in assumptions_raw for key in ("supplier_shipping", "domestic_shipping", "international_shipping")):
        missing.append("shipping")
    if missing:
        unavailable = {"status": "unavailable", "missing_inputs": sorted(set(missing))}
        return {"best": unavailable, "base": unavailable, "worst": unavailable}, unavailable, missing
    lane = _lane(candidate, currency)
    price = _money(price_value, currency=currency, candidate=candidate, area="demand", field_name="price")
    product_cost = _money(cost_value, currency=currency, candidate=candidate, area="supply", field_name="product_cost")
    assumption_values: dict[str, Any] = {}
    money_fields = {"supplier_shipping", "domestic_shipping", "international_shipping", "brokerage_fee", "payment_fee_fixed", "platform_fee_fixed", "ad_spend", "cac"}
    for key, value in assumptions_raw.items():
        if key in money_fields:
            assumption_values[key] = _money(value, currency=currency, candidate=candidate, area="economics", field_name=key)
        elif key in UnitEconomicsAssumptions.__dataclass_fields__:
            assumption_values[key] = _decimal(value, key)
    assumptions = UnitEconomicsAssumptions(**assumption_values, evidence_refs=tuple(ref for ref in (_evidence_ref(candidate, "economics"),) if ref))
    try:
        results = calculate_scenarios(price, product_cost, lane=lane, assumptions=assumptions, overrides=raw.get("scenario_overrides"))
    except (EconomicsError, OpportunityDiscoveryError):
        malformed = {"status": "malformed", "error": "economics_contract_rejected"}
        return {"best": malformed, "base": malformed, "worst": malformed}, malformed, ["economics_contract_rejected"]
    ordered = {"best": results["upside"].to_dict(), "base": results["base"].to_dict(), "worst": results["downside"].to_dict()}
    all_missing = sorted({name for item in results.values() for name in item.missing_inputs})
    if all_missing:
        missing.extend(all_missing)
    return ordered, ordered["base"], sorted(set(missing))


def _service_scenarios(candidate: OpportunityCandidate) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    raw = candidate.economics
    scenario_inputs = raw.get("scenarios", {})
    if not isinstance(scenario_inputs, Mapping):
        raise OpportunityDiscoveryError("invalid_service_scenarios")
    missing: list[str] = []
    outputs: dict[str, Any] = {}
    for name in ("best", "base", "worst"):
        values = scenario_inputs.get(name)
        if not isinstance(values, Mapping):
            missing.append(f"{name}_scenario")
            outputs[name] = {"status": "unavailable", "missing_inputs": [f"{name}_scenario"]}
            continue
        required = ("service_fee", "ad_spend", "contribution_margin", "roas_before", "roas_after", "cac_before", "cac_after", "delivery_hours", "delivery_cost", "tooling_cost", "pass_through_cost", "revision_reserve")
        absent = [key for key in required if values.get(key) is None]
        if absent:
            missing.extend(f"{name}.{key}" for key in absent)
            outputs[name] = {"status": "unavailable", "missing_inputs": absent}
            continue
        currency = str(values.get("currency", raw.get("currency", "USD"))).upper()
        try:
            service_kwargs = {
                "ad_spend": _money(values["ad_spend"], currency=currency, candidate=candidate, area="economics", field_name="ad_spend"),
                "contribution_margin": _decimal(values["contribution_margin"], "contribution_margin"),
                "roas_before": _decimal(values["roas_before"], "roas_before"),
                "roas_after": _decimal(values["roas_after"], "roas_after"),
                "cac_before": _money(values["cac_before"], currency=currency, candidate=candidate, area="economics", field_name="cac_before"),
                "cac_after": _money(values["cac_after"], currency=currency, candidate=candidate, area="economics", field_name="cac_after"),
                "delivery_hours": _decimal(values["delivery_hours"], "delivery_hours"),
                "capacity_hours": _decimal(values["capacity_hours"], "capacity_hours") if values.get("capacity_hours") is not None else None,
                "delivery_cost": _money(values["delivery_cost"], currency=currency, candidate=candidate, area="economics", field_name="delivery_cost") if values.get("delivery_cost") is not None else None,
                "tooling_cost": _money(values["tooling_cost"], currency=currency, candidate=candidate, area="economics", field_name="tooling_cost") if values.get("tooling_cost") is not None else None,
                "pass_through_cost": _money(values["pass_through_cost"], currency=currency, candidate=candidate, area="economics", field_name="pass_through_cost") if values.get("pass_through_cost") is not None else None,
                "target_monthly_contribution": _money(values["target_monthly_contribution"], currency=currency, candidate=candidate, area="economics", field_name="target_monthly_contribution") if values.get("target_monthly_contribution") is not None else None,
                "client_value_created": _money(values["client_value_created"], currency=currency, candidate=candidate, area="economics", field_name="client_value_created") if values.get("client_value_created") is not None else None,
                "evidence_refs": tuple(ref for ref in (_evidence_ref(candidate, "economics"),) if ref),
                "refund_revision_reserve": _money(values["revision_reserve"], currency=currency, candidate=candidate, area="economics", field_name="revision_reserve"),
            }
            service = calculate_service_economics(
                candidate.candidate_id,
                _money(values["service_fee"], currency=currency, candidate=candidate, area="economics", field_name="service_fee"),
                **service_kwargs,
            )
        except (EconomicsError, OpportunityDiscoveryError):
            outputs[name] = {"status": "malformed", "error": "economics_contract_rejected"}
            missing.append(f"{name}.economics")
        else:
            outputs[name] = service.to_dict()
    base = outputs.get("base", {"status": "unavailable"})
    return outputs, base, sorted(set(missing))


def _economics(candidate: OpportunityCandidate) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    if candidate.offering_kind in {"service", "hybrid"} and candidate.economics.get("scenarios"):
        return _service_scenarios(candidate)
    if candidate.offering_kind == "service":
        return {"status": "unavailable", "missing_inputs": ["service_scenarios"]}, {"status": "unavailable"}, ["service_scenarios"]
    return _unit_scenarios(candidate)


def _experiment(candidate: OpportunityCandidate, gaps: Sequence[str], blockers: Sequence[str]) -> ValidationExperiment:
    if any("supplier" in item or "supply" in item for item in (*gaps, *blockers)):
        question = "Can a sanitized supplier record prove availability, cost, and delivery for this candidate?"
        evidence = ("supplier identity", "cost", "availability", "delivery")
    elif any("shipping" in item or "freight" in item for item in (*gaps, *blockers)):
        question = "Does bounded freight evidence preserve a non-negative landed contribution?"
        evidence = ("shipping quote", "lane", "delivery promise")
    elif any("demand" in item or "buyer" in item for item in (*gaps, *blockers)):
        question = "Can sanitized market or consumer evidence establish reachable buyer pain?"
        evidence = ("buyer signal", "pain evidence", "source freshness")
    else:
        question = "Which missing evidence would change the offline decision?"
        evidence = tuple(sorted(set(gaps))) or ("independent evidence",)
    return ValidationExperiment(
        f"experiment-{candidate.candidate_id}",
        question,
        "offline_sanitized_evidence_review",
        evidence,
        {"required_evidence_count": 1, "decision_change": "all fatal gates clear"},
        {"decision_change": "retain_block_or_reject"},
        "iterate only when new bounded evidence changes a named blocker; otherwise stop",
        {"currency": "unknown", "amount": "unknown", "status": "unavailable", "no_spend": True},
    )


def _synthesis(candidate: OpportunityCandidate) -> dict[str, Any]:
    if candidate.offering_kind not in {"product", "hybrid"}:
        return {"status": "not_applicable", "authority": "evaluation.commerce.opportunity_synthesis.build_product_opportunity_synthesis"}
    market = candidate.reports.get("marketplace")
    supplier = candidate.reports.get("supplier")
    consumer = candidate.reports.get("consumer")
    if not any(isinstance(item, Mapping) for item in (market, supplier, consumer)):
        return {"status": "unavailable", "authority": "evaluation.commerce.opportunity_synthesis.build_product_opportunity_synthesis"}
    for report in (market, supplier, consumer):
        if not isinstance(report, Mapping) or not isinstance(report.get("candidates"), list):
            continue
        if not any(isinstance(item, Mapping) and item.get("candidate_id") == candidate.candidate_id for item in report["candidates"]):
            return {
                "status": "malformed",
                "reason": "report_candidate_identity_mismatch",
                "authority": "evaluation.commerce.opportunity_synthesis.build_product_opportunity_synthesis",
            }
    report = build_product_opportunity_synthesis(
        market if isinstance(market, Mapping) else None,
        supplier if isinstance(supplier, Mapping) else None,
        consumer if isinstance(consumer, Mapping) else None,
    ).to_dict()
    candidate_report = next(
        (item for item in report.get("candidates", []) if isinstance(item, Mapping) and item.get("candidate_id") == candidate.candidate_id),
        None,
    )
    if candidate_report is None and any(isinstance(item, Mapping) and isinstance(item.get("candidates"), list) for item in (market, supplier, consumer)):
        return {
            "status": "malformed",
            "reason": "report_candidate_identity_mismatch",
            "authority": "evaluation.commerce.opportunity_synthesis.build_product_opportunity_synthesis",
        }
    score = candidate_report.get("score", {}) if isinstance(candidate_report, Mapping) else {}
    recommendation = score.get("recommendation", {}) if isinstance(score, Mapping) else {}
    risk_profile = score.get("risk_profile", {}) if isinstance(score, Mapping) else {}
    if candidate_report is not None:
        return {
            "status": "derived",
            "authority": "evaluation.commerce.opportunity_synthesis.build_product_opportunity_synthesis",
            "candidate_id": candidate.candidate_id,
            "combined_opportunity_score": score.get("combined_opportunity_score", candidate_report.get("combined_opportunity", 0)),
            "supplier_feasibility": score.get("supplier_feasibility", candidate_report.get("supplier_feasibility", 0)),
            "consumer_attention": score.get("consumer_attention", candidate_report.get("consumer_attention", 0)),
            "marketplace_opportunity": score.get("marketplace_opportunity", candidate_report.get("marketplace_opportunity", 0)),
            "recommendation": recommendation.get("code", candidate_report.get("combined_recommendation", "hold_for_manual_review")) if isinstance(recommendation, Mapping) else "hold_for_manual_review",
            "risk_profile": risk_profile if isinstance(risk_profile, Mapping) else {},
        }
    return {
        "status": "derived",
        "authority": "evaluation.commerce.opportunity_synthesis.build_product_opportunity_synthesis",
        "candidate_id": candidate.candidate_id,
        "combined_opportunity_score": report.get("combined_opportunity_score", 0),
        "supplier_feasibility": report.get("supplier_feasibility", 0),
        "consumer_attention": report.get("consumer_attention", 0),
        "marketplace_opportunity": report.get("marketplace_opportunity", 0),
        "recommendation": report.get("overall_recommendation", "hold_for_manual_review"),
        "risk_profile": report.get("risk_profile", {}),
    }


def _governor(candidate: OpportunityCandidate, synthesis: Mapping[str, Any], readiness: str, workspace_id: str) -> dict[str, Any]:
    score = float(synthesis.get("combined_opportunity_score", 0) or 0)
    supplier = float(synthesis.get("supplier_feasibility", 0) or 0)
    attention = float(synthesis.get("consumer_attention", 0) or 0)
    request = ExecutionDecisionRequest(
        request_id=f"opportunity-screen-{candidate.candidate_id}",
        action_type="screen_product_opportunities",
        domain="intelligence",
        owner_department="intelligence",
        workspace_id=workspace_id or "internal-opportunity-discovery",
        evidence_score=score,
        opportunity_score=score,
        supplier_score=supplier,
        attention_score=attention,
        unit_economics_score=1.0 if readiness in {"acceptable", "attractive"} else 0.0,
        supplier_proof=False,
        trustos_decision="allow",
        workspace_decision="allow",
    )
    result = evaluate_execution_request(request)
    return {
        "authority": "evaluation.companyos.resource_execution_governor.evaluate_execution_request",
        "action_type": result.action_type,
        "outcome": result.outcome,
        "reason": result.reason,
        "blockers": list(result.blockers),
        "simulated_only": result.simulated_only,
    }


def _client_export(candidate: OpportunityCandidate, decision: Mapping[str, Any], *, workspace: Any = None, registry: Any = None, run_id: str) -> dict[str, Any]:
    payload = {
        "workspace_id": getattr(workspace, "workspace_id", None),
        "status": "review_required" if decision["readiness"] != "ready" else "evidence_review",
        "blockers": list(decision["blockers"]),
        "evidence_required": list(decision["evidence_gaps"]),
        "approvals_required": ["human evidence review"],
        "next_actions": [decision["experiment"]["question"]],
    }
    if workspace is None or registry is None:
        return {"status": "unavailable", "reason": "registered_workspace_required", "payload": payload}
    try:
        export = export_client_evidence(
            workspace=workspace,
            registry=registry,
            provenance=f"derived://opportunity-discovery/{run_id}",
            evidence_state="requires_review",
            payload=payload,
        )
    except Exception:
        return {"status": "blocked", "reason": "trustos_export_rejected"}
    return {"status": "validated", "authority": "evaluation.trustos.client_workspace_isolation.export_client_evidence", "fingerprint": export.fingerprint, "payload": export.payload}


def _decision(candidate: OpportunityCandidate, *, mode: str, workspace: Any, registry: Any, run_id: str) -> OpportunityDecision:
    gaps, blockers, classes = _evidence_gaps(candidate)
    metadata = candidate.metadata
    if metadata.get("restricted_category") or metadata.get("legal_status") in {"restricted", "blocked"}:
        blockers.append("restricted_or_legal_category")
    if metadata.get("reachable_buyer") is False:
        blockers.append("no_reachable_buyer")
    elif metadata.get("reachable_buyer") is not True:
        gaps.append("reachable_buyer_evidence_unavailable")
    if metadata.get("operational_risk") in {"unacceptable", "blocked"} or metadata.get("compliance_status") in {"unacceptable", "blocked"}:
        blockers.append("unacceptable_compliance_or_operational_risk")
    supply_evidence = [item for item in candidate.evidence if item.area in {"supply", "supplier"}]
    if candidate.offering_kind in {"product", "hybrid"} and not supply_evidence and not candidate.reports.get("supplier"):
        blockers.append("supply_unproven")
        gaps.append("supplier_evidence_unavailable")
    if any(item.source_type == "supplier_claim" for item in supply_evidence):
        blockers.append("supplier_claim_not_verification")
    scenarios, base, economics_missing = _economics(candidate)
    gaps.extend(economics_missing)
    if base.get("status") in {"unavailable", "malformed"}:
        blockers.append("economics_unavailable")
    contribution = base.get("contribution_after_cac") or base.get("contribution")
    if isinstance(contribution, Mapping):
        try:
            if _decimal(contribution.get("amount"), "contribution") < 0:
                blockers.append("structurally_negative_economics")
        except OpportunityDiscoveryError:
            blockers.append("economics_malformed")
    elif isinstance(contribution, str) and contribution.startswith("-"):
        blockers.append("structurally_negative_economics")
    if not candidate.evidence:
        gaps.append("insufficient_evidence")
    synthesis = _synthesis(candidate)
    if synthesis.get("status") == "unavailable" and candidate.offering_kind in {"product", "hybrid"}:
        gaps.append("marketplace_supplier_consumer_reports_unavailable")
    if synthesis.get("status") == "malformed":
        blockers.append(str(synthesis.get("reason", "malformed_synthesis_report")))
        gaps.append("malformed_synthesis_report")
    gaps = sorted(set(gaps))
    blockers = sorted(set(blockers))
    fatal = tuple(item for item in blockers if item in {"restricted_or_legal_category", "no_reachable_buyer", "supply_unproven", "supplier_claim_not_verification", "structurally_negative_economics", "unacceptable_compliance_or_operational_risk", "economics_malformed", "report_candidate_identity_mismatch"})
    if fatal:
        recommendation = "blocked"
        readiness = "blocked"
    elif gaps:
        recommendation = "needs_evidence"
        readiness = "not_ready"
    else:
        score = float(synthesis.get("combined_opportunity_score", 0) or 0)
        recommendation = "attractive" if score >= 0.68 else "acceptable"
        readiness = "ready"
    experiment = _experiment(candidate, gaps, blockers)
    provisional = {
        "readiness": readiness,
        "blockers": blockers,
        "evidence_gaps": gaps,
        "experiment": experiment.to_dict(),
    }
    governor = _governor(candidate, synthesis, readiness, getattr(workspace, "workspace_id", ""))
    trustos = _client_export(candidate, provisional, workspace=workspace, registry=registry, run_id=run_id)
    metrics = {
        "synthesis_score": synthesis.get("combined_opportunity_score"),
        "offering_kind": candidate.offering_kind,
        "evidence_confidence": round(len([item for item in candidate.evidence if item.status == "observed_fact"]) / max(1, len(candidate.evidence)), 4),
        "economics_status": base.get("status", "derived"),
        "economics_missing_inputs": economics_missing,
    }
    return OpportunityDecision(candidate.candidate_id, recommendation, readiness, fatal, tuple(blockers), tuple(gaps), tuple(classes), metrics, scenarios, ("supplier evidence", "landed cost", "reachable buyer", "compliance") if any(item in blockers for item in ("supply_unproven", "structurally_negative_economics", "no_reachable_buyer", "unacceptable_compliance_or_operational_risk")) else ("evidence freshness",), experiment, synthesis, governor, trustos, dict(candidate.metadata.get("review_results", {})) if mode == "review-results" else {})


def run_discovery(mode: str, payload: Mapping[str, Any], *, workspace: Any = None, registry: Any = None) -> DiscoveryRun:
    """Run one deterministic offline discovery mode over supplied evidence."""
    if mode not in DISCOVERY_MODES:
        raise OpportunityDiscoveryError("invalid_mode")
    safe = _json_safe(payload)
    # Discovery may only derive candidates from an explicitly supplied seed;
    # it never invents a category, market, or business idea.
    candidates_raw = safe.get("candidates") or safe.get("evidence_candidates", [])
    if not isinstance(candidates_raw, list) or len(candidates_raw) > MAX_CANDIDATES:
        raise OpportunityDiscoveryError("candidate_bounds_exceeded")
    candidates = tuple(sorted((_normalize_candidate(item, index) for index, item in enumerate(candidates_raw)), key=lambda item: item.candidate_id))
    if len({item.candidate_id for item in candidates}) != len(candidates):
        raise OpportunityDiscoveryError("duplicate_candidate_id")
    if mode in {"evaluate", "validate", "review-results"} and len(candidates) != 1:
        raise OpportunityDiscoveryError("single_candidate_mode_requires_one_candidate")
    if mode == "compare" and len(candidates) < 2:
        raise OpportunityDiscoveryError("compare_mode_requires_two_candidates")
    run_id = _ensure_id(safe.get("run_id", "opportunity-discovery-v1"), "run_id")
    decisions = tuple(_decision(item, mode=mode, workspace=workspace, registry=registry, run_id=run_id) for item in candidates)
    ready_decisions = [item for item in decisions if item.readiness == "ready"]
    ranked = tuple(
        item.candidate_id
        for item in sorted(
            ready_decisions,
            key=lambda value: (-_decimal(value.metrics.get("synthesis_score"), "synthesis_score") if value.metrics.get("synthesis_score") is not None else Decimal("1"), value.candidate_id),
        )
    )
    blockers = sorted({blocker for item in decisions for blocker in item.blockers})
    if not candidates:
        status, next_action = "unavailable", "supply sanitized candidates or evidence-backed candidate generation inputs"
    elif all(item.readiness == "blocked" for item in decisions):
        status, next_action = "blocked", "resolve a named fatal gate before comparing candidates"
    elif any(item.readiness != "ready" for item in decisions):
        status, next_action = "needs_evidence", "run the cheapest bounded evidence experiment named for the leading candidate"
    else:
        status, next_action = "ready_for_review", "review the deterministic evidence matrix; no external action is authorized"
    base = DiscoveryRun("opportunity-discovery-v1", mode, status, "actual_executed", candidates, decisions, ranked, tuple(blockers), next_action, {"read_only": True, "network_calls": False, "provider_calls": False, "credentials_present": False, "orders_created": False, "payments_created": False, "ads_launched": False, "publishing": False, "database_writes": False, "launch_authorized": False})
    if len(_canonical(base.to_dict(include_fingerprint=False)).encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise OpportunityDiscoveryError("output_size_exceeded")
    return DiscoveryRun(base.run_version, base.mode, base.status, base.execution_classification, base.candidates, base.decisions, base.ranked_candidate_ids, base.blockers, base.next_best_action, base.safety, _fingerprint(base.to_dict(include_fingerprint=False)))


def render_markdown(report: DiscoveryRun | Mapping[str, Any]) -> str:
    data = report.to_dict() if isinstance(report, DiscoveryRun) else dict(report)
    lines = ["# Opportunity Discovery", "", f"- Mode: **{data.get('mode', 'unknown')}**", f"- Status: **{data.get('status', 'unknown')}**", f"- Execution: **{data.get('execution_classification', 'unknown')}**", f"- Fingerprint: `{data.get('fingerprint', 'unavailable')}`", "", "## Decisions", "", "| Candidate | Recommendation | Readiness | Blockers |", "|---|---|---|---|"]
    for item in sorted(data.get("decisions", []), key=lambda value: str(value.get("candidate_id", ""))):
        lines.append(f"| {item.get('candidate_id', '')} | **{item.get('recommendation', '')}** | {item.get('readiness', '')} | {', '.join(item.get('blockers', [])) or 'none recorded'} |")
    lines.extend(["", "## Safety", "", "No ads, spend, publishing, outreach, orders, payments, inventory, provider activation, or launch authority is created by this report.", "", "## Next Action", "", str(data.get("next_best_action", "review evidence")), ""])
    return "\n".join(lines)


__all__ = [
    "DISCOVERY_MODES", "EVIDENCE_CLASSES", "EVIDENCE_STATUSES", "DiscoveryRun", "OpportunityCandidate", "OpportunityDecision", "OpportunityDiscoveryError", "OpportunityEvidence", "ValidationExperiment", "load_payload", "render_markdown", "run_discovery",
]
