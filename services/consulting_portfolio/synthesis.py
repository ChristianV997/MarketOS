"""Deterministic, evidence-preserving consulting portfolio synthesis."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence


_AREA_KEYS = (
    "product_service_assessments",
    "market_research",
    "demand_consumer_attention",
    "supplier_logistics",
    "unit_service_economics",
    "customer_intelligence",
    "marketing_publicity_strategy",
    "creative_testing",
    "blockers",
    "evidence_gaps",
    "repeated_risks",
    "package_readiness",
    "limitations",
    "assumptions",
    "recommended_sequence",
    "next_best_action",
    "human_review",
    "decision_boundary",
)
_FORBIDDEN_TERMS = {
    "launch_authorized", "publishing_authorized", "spending_authorized", "messaging_authorized",
    "orders_authorized", "payments_authorized", "supplier_authorized", "live_authorized",
}
_CLIENT_FORBIDDEN_KEYS = {
    "internal_prompt", "internal_formula", "internal_heuristic", "raw_provider_payload", "raw_payload",
    "api_key", "access_token", "password", "credentials", "publishing_authorized", "payment_authorized",
    "spending_authorized", "orders_authorized", "supplier_authorized", "launch_authorized",
}


class PortfolioInputError(ValueError):
    """Raised when component report metadata or safety claims are invalid."""


@dataclass(frozen=True)
class PortfolioSynthesis:
    schema_version: str
    status: str
    package_readiness: str
    report_ids: list[str]
    report_fingerprints: dict[str, str]
    services: list[str]
    capabilities: dict[str, str]
    facts_by_area: dict[str, list[str]]
    provenance_by_area: dict[str, list[dict[str, str]]]
    assumptions: list[str]
    stale_reports: list[str]
    conflicting_reports: list[str]
    blockers: list[str]
    evidence_gaps: list[str]
    repeated_risks: list[str]
    recommended_sequence: list[str]
    next_best_actions: list[str]
    limitations: list[str]
    human_review: dict[str, Any]
    decision_boundary: dict[str, Any]
    safety: dict[str, Any]
    client_safe_projection: dict[str, Any]
    fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())


def synthesize_portfolio(reports: Sequence[Mapping[str, Any]]) -> PortfolioSynthesis:
    normalized = _normalize_reports(reports)
    report_ids = [item["report_id"] for item in normalized]
    report_fingerprints = {item["report_id"]: item["fingerprint"] for item in normalized}
    services = sorted({item["service"] for item in normalized})
    facts: dict[str, set[str]] = {key: set() for key in _AREA_KEYS}
    provenance: dict[str, set[tuple[str, str]]] = {key: set() for key in _AREA_KEYS}
    capabilities: dict[str, str] = {}
    assumptions: set[str] = set()
    stale_reports: list[str] = []
    conflicting_reports: list[str] = []
    limitations: set[str] = set()

    for report in normalized:
        service = report["service"]
        state = report["status"]
        previous = capabilities.get(service)
        capabilities[service] = _merge_capability(previous, state)
        if report.get("stale"):
            stale_reports.append(report["report_id"])
        if report.get("conflicting"):
            conflicting_reports.append(report["report_id"])
        for key, values in report["facts"].items():
            if key not in facts:
                continue
            values_as_text = _string_values(values)
            facts[key].update(values_as_text)
            provenance[key].update((item, report["report_id"]) for item in values_as_text)
            if key == "assumptions":
                assumptions.update(_string_values(values))
            if key == "limitations":
                limitations.update(_string_values(values))
        if state == "unavailable":
            limitations.add(f"{service} report unavailable")
        if state == "partial":
            limitations.add(f"{service} evidence is partial")

    stale_reports.sort()
    conflicting_reports.sort()
    blockers = set(facts["blockers"])
    evidence_gaps = set(facts["evidence_gaps"])
    if stale_reports:
        blockers.add("stale evidence requires refresh")
    if conflicting_reports:
        blockers.add("conflicting evidence requires reconciliation")
    if not normalized:
        limitations.add("no component reports supplied")
        blockers.add("component report inputs are unavailable")
    for service, state in capabilities.items():
        if state in {"partial", "unavailable"}:
            evidence_gaps.add(f"{service} capability is {state}")

    readiness = "ready_for_review" if normalized and not blockers and not evidence_gaps else "not_ready"
    status = "unavailable" if not normalized else "human_review_required"
    sequence = sorted(facts["recommended_sequence"])
    actions = sorted(facts["next_best_action"])
    limitations.update(facts["limitations"])
    result_data = {
        "schema_version": "consulting-portfolio-synthesis-v1",
        "status": status,
        "package_readiness": readiness,
        "report_ids": report_ids,
        "report_fingerprints": report_fingerprints,
        "services": services,
        "capabilities": capabilities,
        "facts_by_area": {key: sorted(values) for key, values in facts.items() if values},
        "provenance_by_area": {
            key: [{"fact": fact, "report_id": report_id} for fact, report_id in sorted(entries)]
            for key, entries in provenance.items()
            if entries
        },
        "assumptions": sorted(assumptions),
        "stale_reports": stale_reports,
        "conflicting_reports": conflicting_reports,
        "blockers": sorted(blockers),
        "evidence_gaps": sorted(evidence_gaps),
        "repeated_risks": sorted(facts["repeated_risks"]),
        "recommended_sequence": sequence,
        "next_best_actions": actions,
        "limitations": sorted(limitations),
        "human_review": {"required": True, "state": "pending", "reason": "portfolio synthesis is advisory and evidence-preserving"},
        "decision_boundary": {"scoring": "not_performed", "opportunity_synthesis": "not_performed", "facts_aggregated": True},
        "safety": {"read_only": True, "network_calls": False, "external_actions_authorized": False, "spending": False, "publishing": False, "messaging": False, "orders": False, "payments": False, "suppliers": False, "launch": False},
        "client_safe_projection": None,
    }
    client_projection = _client_projection(
        status=status,
        package_readiness=readiness,
        report_ids=report_ids,
        report_fingerprints=report_fingerprints,
        services=services,
        capabilities=capabilities,
        facts=facts,
        provenance=provenance,
        blockers=blockers,
        evidence_gaps=evidence_gaps,
        limitations=limitations,
        sequence=sequence,
        actions=actions,
    )
    result_data["client_safe_projection"] = client_projection
    fingerprint = _sha256(result_data)
    return PortfolioSynthesis(fingerprint=fingerprint, **result_data)


def _normalize_reports(reports: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(reports, Sequence) or isinstance(reports, (str, bytes)):
        raise PortfolioInputError("reports must be a sequence")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for report in reports:
        if not isinstance(report, Mapping):
            raise PortfolioInputError("each report must be a mapping")
        report_id = str(report.get("report_id", "")).strip()
        fingerprint = str(report.get("fingerprint", "")).strip()
        service = str(report.get("service", "")).strip()
        if not report_id:
            raise PortfolioInputError("report_id is required")
        if report_id in seen:
            raise PortfolioInputError(f"duplicate report_id: {report_id}")
        if not fingerprint:
            raise PortfolioInputError(f"fingerprint is required for {report_id}")
        if not service:
            raise PortfolioInputError(f"service is required for {report_id}")
        facts = report.get("facts", {})
        if not isinstance(facts, Mapping):
            raise PortfolioInputError(f"facts must be a mapping for {report_id}")
        _reject_external_claims(report)
        _reject_sensitive_content(facts)
        seen.add(report_id)
        normalized.append({
            "report_id": report_id,
            "fingerprint": fingerprint,
            "service": service,
            "status": str(report.get("status", "unavailable")).strip().lower() or "unavailable",
            "observed_at": str(report.get("observed_at", "")),
            "stale": bool(report.get("stale", False)),
            "conflicting": bool(report.get("conflicting", False)),
            "facts": {str(key): value for key, value in facts.items()},
        })
    return sorted(normalized, key=lambda item: item["report_id"])


def _reject_external_claims(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key).strip().lower()
            if key_text in _FORBIDDEN_TERMS or key_text.endswith("_authorized"):
                if bool(child) or child not in (None, "", [], {}, False):
                    raise PortfolioInputError(f"external action claim rejected: {key}")
            _reject_external_claims(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _reject_external_claims(child)


def _reject_sensitive_content(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).strip().lower() in _CLIENT_FORBIDDEN_KEYS:
                raise PortfolioInputError(f"sensitive field rejected: {key}")
            _reject_sensitive_content(child)
    elif isinstance(value, (list, tuple, set)):
        for child in value:
            _reject_sensitive_content(child)


def _client_projection(**data: Any) -> dict[str, Any]:
    projection = {
        "schema_version": "consulting-portfolio-client-safe-v1",
        "status": data["status"],
        "package_readiness": data["package_readiness"],
        "report_ids": list(data["report_ids"]),
        "report_fingerprints": dict(data["report_fingerprints"]),
        "services": list(data["services"]),
        "capabilities": dict(data["capabilities"]),
        "facts_by_area": _safe_fact_projection(data["facts"]),
        "provenance_by_area": _safe_provenance_projection(data["provenance"]),
        "blockers": sorted(data["blockers"]),
        "evidence_gaps": sorted(data["evidence_gaps"]),
        "limitations": sorted(data["limitations"]),
        "recommended_sequence": list(data["sequence"]),
        "next_best_actions": list(data["actions"]),
        "human_review": {"required": True, "state": "pending"},
        "external_actions_authorized": False,
    }
    if any(str(key).lower() in _CLIENT_FORBIDDEN_KEYS for key in projection):
        raise PortfolioInputError("client-safe projection contains forbidden field")
    return projection


def _safe_fact_projection(facts: Mapping[str, set[str]]) -> dict[str, list[str]]:
    safe: dict[str, list[str]] = {}
    for key, values in facts.items():
        if key == "assumptions" or not values:
            continue
        safe_values = sorted(value for value in values if isinstance(value, str))
        if safe_values:
            safe[key] = safe_values
    return safe


def _safe_provenance_projection(provenance: Mapping[str, set[tuple[str, str]]]) -> dict[str, list[dict[str, str]]]:
    safe: dict[str, list[dict[str, str]]] = {}
    for key, entries in provenance.items():
        if not entries:
            continue
        safe[key] = [
            {"fact": fact, "report_id": report_id}
            for fact, report_id in sorted(entries)
            if isinstance(fact, str) and isinstance(report_id, str)
        ]
    return {key: entries for key, entries in safe.items() if entries}


def _merge_capability(previous: str | None, current: str) -> str:
    rank = {"available": 0, "partial": 1, "unavailable": 2}
    current = current if current in rank else "unavailable"
    if previous is None or rank[current] > rank[previous]:
        return current
    return previous


def _string_values(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value.strip()} if value.strip() else set()
    if isinstance(value, (list, tuple, set)):
        return {item.strip() for item in value if isinstance(item, str) and item.strip()}
    return set()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()
