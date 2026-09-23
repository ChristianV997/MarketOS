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
_RESULT_STATUSES = frozenset({"successful", "failed", "inconclusive", "invalid", "simulated"})
_EVIDENCE_STATES = frozenset({"unknown", "missing", "observed", "verified", "fixture", "manual_import", "simulated", "stale", "future", "conflicting", "rejected"})
_OFFERING_KINDS = frozenset({"product", "service", "hybrid", "unknown"})
_EXTERNAL_MARKERS = frozenset({"advertise", "advertising", "ad_launch", "launch_ad", "publish", "publishing", "outreach", "message", "messaging", "send", "order", "payment", "inventory", "provider_call", "customer_contact", "contact_customer"})
_SECRET_MARKERS = frozenset({"api_key", "private_key", "password", "token", "access_token", "refresh_token", "authorization", "cookie", "credential", "raw_payload", "raw_html", "client_secret"})


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
    if isinstance(value, (tuple, list, set)):
        return [_clean(item) for item in value]
    return value


@dataclass(frozen=True)
class NormalizedOpportunityInput:
    """Typed boundary for sanitized discovery and geographic-research reports."""

    offering_kind: str
    candidate: dict[str, Any]
    candidate_evidence: tuple[dict[str, Any], ...]
    geographic_context: dict[str, Any]


def normalize_opportunity_inputs(payload: Mapping[str, Any]) -> NormalizedOpportunityInput:
    """Adapt normalized reports without importing their discovery implementations."""
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


def _money(value: Any, name: str, currency: str, *, missing: list[str], explicit_zero_name: str | None = None) -> Money:
    if value is None:
        missing.append(name)
        return Money.zero(currency, source=f"assumed_{name}")
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
        "geography": {"kind": geography_kind, "origin": geography.get("origin", "unknown"), "destination": geography.get("destination", "unknown"), "uncertainty": list(sorted(uncertainty))},
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
                f"- Offering kind: {self.offering_kind}",
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
    economics_results = calculate_scenarios(price, product_cost, assumptions=UnitEconomicsAssumptions(cac=cac, evidence_refs=refs))
    economics = {"scenarios": {name: item.to_dict() for name, item in economics_results.items()}, "base_cost_state": "missing" if "product_cost" in missing_inputs else "explicit_zero" if product_cost.amount == 0 else "explicit", "missing_inputs": tuple(missing_inputs)}
    evidence = _evidence_summary(payload, as_of_dt)
    market, supplier, consumer = _pillar_reports(payload, evidence)
    opportunity = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    opportunity["scoring_authority"] = "evaluation.commerce.opportunity_synthesis.build_product_opportunity_synthesis"
    result_rows = payload.get("result_statuses") or [((payload.get("result") or {}).get("status") or "simulated")]
    if not isinstance(result_rows, (list, tuple)):
        raise ValidationExperimentInputError("result status must be a list")
    result_statuses = tuple(str(row) for row in result_rows)
    if not result_statuses or any(status not in _RESULT_STATUSES for status in result_statuses):
        raise ValidationExperimentInputError("result status is invalid")
    economics_blocked = bool({"price", "product_cost", "cac"}.intersection(missing_inputs))
    blockers: list[str] = []
    gaps: list[str] = []
    if not payload.get("reachable_buyer", False):
        blockers.append("reachable_buyer")
    if "supplier_evidence" in evidence_required and not isinstance(payload.get("supplier_evidence"), Mapping):
        gaps.append("supplier_evidence")
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
    if "fixture_evidence_not_live" in evidence["limitations"]:
        gaps.append("fixture_evidence_not_live")
    if not payload.get("opportunity_reports") and not payload.get("normalized_candidate") and not any(payload.get(key) for key in ("market_evidence", "supplier_evidence")):
        gaps.append("opportunity_evidence")
    base_after = economics_results["base"].contribution_after_cac.amount
    budget_amount = float(budget_value.get("amount", 0)) if isinstance(budget_value, Mapping) else 0.0
    approval_sim = simulate_action("launch_ad", requested_budget=budget_amount, generated_at="offline-deterministic").to_dict()
    request = ExecutionDecisionRequest(request_id=f"validation-{candidate_id}", action_type="launch_ad_experiment", domain="ads_content", owner_department="validation", workspace_id=workspace_id, requested_amount=budget_amount, hypothesis=hypothesis, success_metric=measurement, kill_threshold=float(thresholds["kill_threshold"]), scale_threshold=float(thresholds["success_threshold"]), sample_size_target=sample_target, approval_state="approved" if payload.get("approval_state") == "approved" else "not_requested", trustos_decision="hard_block", workspace_decision="allow")
    governor = evaluate_execution_request(request).to_dict()
    trustos = evaluate_action("launch_ad", generated_at="offline-deterministic").to_dict()
    workspace = build_client_workspace_isolation_report(workspace_type="client_growth_workspace", payload={"workspace_id": workspace_id, "status": "client_safe", "blockers": tuple(blockers), "evidence_required": tuple(gaps), "approvals_required": ("human_review",), "next_actions": ("review_simulated_result",)}).to_dict()
    if "experiment_budget" in blockers:
        decision = "blocked_missing_budget"
    elif economics_blocked:
        decision = "blocked_missing_economics"
    elif base_after < 0:
        decision = "kill_negative_unit_economics"
    elif "reachable_buyer" in blockers:
        decision = "hold_unreachable_buyer"
    elif any(status == "invalid" for status in result_statuses):
        decision = "reject_invalid_result"
    elif any(status == "successful" for status in result_statuses):
        decision = "advance_to_human_review"
    elif any(status == "failed" for status in result_statuses):
        decision = "kill_failed_result"
    else:
        decision = "iterate_inconclusive_result"
    approval_state = "pending_review" if decision == "advance_to_human_review" else "blocked_by_policy" if blockers or base_after < 0 else "draft"
    limitations = tuple(sorted(set(evidence["limitations"] + (("external_execution_blocked",) if True else ()))))
    safety = {"read_only": True, "network_calls": False, "ads_launched": False, "spend_executed": False, "publishing_performed": False, "outreach_sent": False, "orders_created": False, "payments_created": False, "provider_calls": False, "customer_contact": False, "database_writes": False}
    offering_kind, validation_pipeline = _normalized_opportunity_pipeline(payload, evidence=evidence, economics=economics, result_statuses=result_statuses, decision=decision, gaps=tuple(gaps))
    provisional = ValidationExperimentLedger(workspace_id, candidate_id, hypothesis, segment, channel, test_method, evidence_required, budget, sample_target, str(thresholds["success_threshold"]), str(thresholds["kill_threshold"]), str(thresholds["iterate_threshold"]), measurement, approval_state, result_statuses, decision, tuple(sorted(set(blockers))), tuple(sorted(set(gaps))), limitations, _text(payload.get("provenance"), "provenance", required=True), evidence, economics, {"candidate_id": opportunity.get("top_candidate_id"), "scoring_authority": "evaluation.commerce.opportunity_synthesis.build_product_opportunity_synthesis", "report": opportunity}, approval_sim, governor, trustos, {"workspace_id": workspace_id, "client_safe": True, "safety_summary": workspace.get("safety_summary", {})}, safety, offering_kind=offering_kind, validation_pipeline=validation_pipeline)
    return ValidationExperimentLedger(**{**provisional.__dict__, "fingerprint": _canonical_fingerprint(provisional.to_dict())})
