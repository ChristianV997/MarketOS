from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


class ConsultingEvidenceInputError(ValueError):
    """Stable failure for malformed or unsafe persisted report input."""


_REPORT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{1,127}$")
_FINGERPRINT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{1,255}$")
_WORKSPACE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{1,127}$")
_SENSITIVE_KEYS = {"api_key", "apikey", "access_token", "client_secret", "password", "private_key", "secret", "token"}
_EXTERNAL_MARKERS = (
    "authorized to publish", "authorized to launch", "authorized to spend", "authorized to contact",
    "authorized to order", "authorized to pay", "publish now", "send customer", "create order",
    "capture payment", "refund customer",
)
_CAPABILITY_STATES = {"available", "partial", "unavailable", "unknown"}
_REPORT_STATUSES = {"completed", "partial", "unavailable", "blocked", "draft", "empty"}


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _walk_unsafe(value: Any, path: str = "") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ConsultingEvidenceInputError("invalid object key")
            normalized = key.casefold().replace("-", "_").replace(" ", "_")
            if normalized in _SENSITIVE_KEYS or any(marker in normalized for marker in ("credential", "secret", "authorization", "raw_payload")):
                raise ConsultingEvidenceInputError("sensitive content rejected")
            _walk_unsafe(child, f"{path}.{key}".strip("."))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _walk_unsafe(child, f"{path}[{index}]")
    elif isinstance(value, str):
        lowered = value.casefold()
        if any(marker in lowered for marker in _EXTERNAL_MARKERS):
            raise ConsultingEvidenceInputError("external action claim rejected")
        if any(ord(char) < 32 and char not in "\n\t\r" for char in value):
            raise ConsultingEvidenceInputError("control character rejected")


def _text(value: Any, field: str, *, optional: bool = False) -> str:
    if optional and value in (None, ""):
        return ""
    if not isinstance(value, str) or not value.strip() or any(ord(char) < 32 for char in value):
        raise ConsultingEvidenceInputError(f"invalid {field}")
    return value.strip()


def _list_of_text(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ConsultingEvidenceInputError(f"invalid {field}")
    return sorted({item.strip() for item in value})


def _safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _safe_value(child) for key, child in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [_safe_value(child) for child in value]
    raise ConsultingEvidenceInputError("unsupported fact value")


def _normalize_report(report: Mapping[str, Any], workspace_id: str | None) -> dict[str, Any]:
    if not isinstance(report, Mapping):
        raise ConsultingEvidenceInputError("report must be an object")
    _walk_unsafe(report)
    report_id = _text(report.get("report_id"), "report_id")
    if not _REPORT_ID.fullmatch(report_id):
        raise ConsultingEvidenceInputError("invalid report_id")
    fingerprint = _text(report.get("fingerprint"), "fingerprint")
    if not _FINGERPRINT.fullmatch(fingerprint):
        raise ConsultingEvidenceInputError("invalid fingerprint")
    report_workspace = _text(report.get("workspace_id"), "workspace_id")
    if workspace_id is not None and report_workspace != workspace_id:
        raise ConsultingEvidenceInputError("workspace mismatch")
    service_name = _text(report.get("service_name"), "service_name")
    status = _text(report.get("status", "unknown"), "status")
    if status not in _REPORT_STATUSES:
        raise ConsultingEvidenceInputError("invalid status")
    capabilities = report.get("capabilities", {})
    if not isinstance(capabilities, Mapping):
        raise ConsultingEvidenceInputError("invalid capabilities")
    return {
        "report_id": report_id,
        "fingerprint": fingerprint,
        "workspace_id": report_workspace,
        "service_name": service_name,
        "status": status,
        "capabilities": capabilities,
        "assumptions": _list_of_text(report.get("assumptions"), "assumptions"),
        "limitations": _list_of_text(report.get("limitations"), "limitations"),
    }


def _report_sort_key(report: Mapping[str, Any]) -> tuple[str, str]:
    return str(report["report_id"]), str(report["fingerprint"])


@dataclass(frozen=True)
class ConsultingEvidenceRegister:
    workspace_id: str
    status: str
    readiness: bool
    report_refs: list[dict[str, str]]
    capability_states: dict[str, str]
    evidence_by_area: dict[str, list[dict[str, Any]]]
    assumptions: list[str]
    limitations: list[str]
    gaps: list[str]
    conflicts: list[str]
    human_review: dict[str, Any]
    decision_boundary: dict[str, str]
    safety: dict[str, bool]
    client_safe_projection: dict[str, Any]
    fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "status": self.status,
            "readiness": self.readiness,
            "report_refs": self.report_refs,
            "capability_states": self.capability_states,
            "evidence_by_area": self.evidence_by_area,
            "assumptions": self.assumptions,
            "limitations": self.limitations,
            "gaps": self.gaps,
            "conflicts": self.conflicts,
            "human_review": self.human_review,
            "decision_boundary": self.decision_boundary,
            "safety": self.safety,
            "client_safe_projection": self.client_safe_projection,
            "fingerprint": self.fingerprint,
        }


def _build_projection(data: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "workspace_id": data["workspace_id"],
        "status": data["status"],
        "readiness": data["readiness"],
        "capability_states": data["capability_states"],
        "evidence_by_area": data["evidence_by_area"],
        "gaps": data["gaps"],
        "conflicts": data["conflicts"],
        "human_review_required": True,
        "external_actions_authorized": False,
    }


def build_component_report_envelope(
    *,
    report_id: str,
    fingerprint: str,
    service: str,
    workspace_id: str,
    status: str,
    observed_at: str = "",
    stale: bool = False,
    conflicting: bool = False,
    facts: Mapping[str, Any] | None = None,
    capabilities: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """The one place a caller builds a persisted-component-report envelope
    that both `services.consulting_portfolio.synthesize_portfolio` and
    `build_evidence_register` accept, closing the envelope mismatch
    between them: `synthesize_portfolio` reads a `service` key,
    `build_evidence_register` reads `service_name` -- this emits both,
    aliased to the same value, plus `workspace_id` and a `status` drawn
    from `build_evidence_register`'s own fixed vocabulary (a strict
    subset `synthesize_portfolio` accepts unconditionally, since it does
    not restrict `status` to a fixed set). Neither consumer is modified;
    this only removes the need for a caller to hand-build two slightly
    different dicts for the same underlying report."""
    if status not in _REPORT_STATUSES:
        raise ConsultingEvidenceInputError(f"status must be one of {sorted(_REPORT_STATUSES)}")
    return {
        "report_id": report_id,
        "fingerprint": fingerprint,
        "service": service,
        "service_name": service,
        "workspace_id": workspace_id,
        "status": status,
        "observed_at": observed_at,
        "stale": stale,
        "conflicting": conflicting,
        "facts": dict(facts or {}),
        "capabilities": dict(capabilities or {}),
    }


def build_evidence_register(
    reports: Sequence[Mapping[str, Any]],
    *,
    workspace_id: str | None = None,
    generated_at: str = "offline-deterministic",
) -> ConsultingEvidenceRegister:
    if not isinstance(reports, (list, tuple)):
        raise ConsultingEvidenceInputError("reports must be a list")
    normalized = [_normalize_report(report, workspace_id) for report in reports]
    normalized.sort(key=_report_sort_key)
    if normalized:
        workspace_id = workspace_id or normalized[0]["workspace_id"]
    workspace_id = _text(workspace_id, "workspace_id")
    if not _WORKSPACE_ID.fullmatch(workspace_id):
        raise ConsultingEvidenceInputError("invalid workspace_id")
    _text(generated_at, "generated_at")

    report_refs = [
        {"report_id": report["report_id"], "fingerprint": report["fingerprint"], "service_name": report["service_name"], "status": report["status"]}
        for report in normalized
    ]
    capability_states: dict[str, str] = {}
    evidence_by_area: dict[str, list[dict[str, Any]]] = {}
    assumptions: set[str] = set()
    limitations: set[str] = set()
    gaps: set[str] = set()
    conflicts: set[str] = set()
    for report in normalized:
        assumptions.update(report["assumptions"])
        limitations.update(report["limitations"])
        for area, raw in sorted(report["capabilities"].items(), key=lambda item: str(item[0])):
            area_name = _text(area, "capability area")
            if not isinstance(raw, Mapping):
                raise ConsultingEvidenceInputError("invalid capability")
            state = _text(raw.get("state", "unknown"), "capability state")
            if state not in _CAPABILITY_STATES:
                raise ConsultingEvidenceInputError("invalid capability state")
            capability_states[area_name] = "partial" if capability_states.get(area_name) == "partial" or state == "partial" else state
            facts = raw.get("facts", {})
            if not isinstance(facts, Mapping):
                raise ConsultingEvidenceInputError("invalid capability facts")
            safe_facts = _safe_value(facts)
            entry = {
                "source_report_id": report["report_id"],
                "source_fingerprint": report["fingerprint"],
                "evidence_state": raw.get("freshness") or state,
                "facts": safe_facts,
                "provenance": _list_of_text(raw.get("provenance"), "provenance"),
                "observed_at": _text(raw.get("observed_at"), "observed_at", optional=True),
            }
            if raw.get("conflicts"):
                entry["evidence_state"] = "conflict"
                conflicts.update(f"{area_name}:{item}" for item in _list_of_text(raw["conflicts"], "conflicts"))
            if entry["evidence_state"] == "stale":
                limitations.add("stale evidence remains unresolved")
            evidence_by_area.setdefault(area_name, []).append(entry)
            for missing in _list_of_text(raw.get("missing"), "missing"):
                gaps.add(f"{area_name}:{missing}")
    for entries in evidence_by_area.values():
        entries.sort(key=lambda item: (item["source_report_id"], item["source_fingerprint"]))
    for report in normalized:
        for area, raw in report["capabilities"].items():
            if isinstance(raw, Mapping) and raw.get("state") in {"partial", "unavailable", "unknown"}:
                gaps.add(str(area))
    status = "empty" if not normalized else "partial" if gaps or conflicts or any(state != "available" for state in capability_states.values()) else "complete"
    readiness = bool(normalized) and status == "complete" and not conflicts
    limitations.update("No scoring, ranking, or decision authority is performed." for _ in [0])
    base = {
        "workspace_id": workspace_id,
        "status": status,
        "readiness": readiness,
        "report_refs": report_refs,
        "capability_states": dict(sorted(capability_states.items())),
        "evidence_by_area": dict(sorted(evidence_by_area.items())),
        "assumptions": sorted(assumptions),
        "limitations": sorted(limitations),
        "gaps": sorted(gaps),
        "conflicts": sorted(conflicts),
        "human_review": {"required": True, "reason": "Evidence and assumptions require human confirmation before client use."},
        "decision_boundary": {"scoring": "not_performed", "authorization": "not_performed"},
        "safety": {"external_actions_authorized": False, "provider_calls_performed": False},
    }
    base["client_safe_projection"] = _build_projection(base)
    fingerprint = hashlib.sha256(_canonical(base).encode("utf-8")).hexdigest()
    return ConsultingEvidenceRegister(**base, fingerprint=fingerprint)
