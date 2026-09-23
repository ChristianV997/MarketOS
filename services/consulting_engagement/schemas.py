"""Typed request and projection contracts for consulting engagements.

This layer describes an engagement and references existing component reports;
it deliberately does not copy their raw findings or calculate economics.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from evaluation.commerce.kernel_integration import replay_fingerprint
from services.consulting_offers import OFFER_IDS
from services.reporting.render import render_markdown_report

OFFERING_KINDS = frozenset({"product", "service", "hybrid", "unknown"})
EVIDENCE_CLASSES = frozenset({
    "fixture", "manual", "manual_import", "observed", "derived", "simulated",
    "simulated_or_planned", "planned", "live", "actual_executed", "unavailable",
})
EVIDENCE_STATES = frozenset({"available", "missing", "stale", "conflicting", "blocked", "unavailable"})
ALLOWED_DELIVERABLES = frozenset({
    "product_research", "unit_economics", "customer_intelligence", "creative_growth",
    "profit_stack_advisor", "service_engagement", "service_delivery", "client_safe_export",
})
SECRET_MARKERS = (
    "sk-", "ghp_", "github_pat_", "bearer ", "-----begin", "api_key", "access_token",
    "private_key", "password", "client_secret", "cookie=", "raw_payload",
)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class SchemaValidationError(ValueError):
    """Stable validation failure without reflecting untrusted values."""


def _safe_text(value: Any, field_name: str, *, required: bool = True, max_length: int = 512) -> str:
    if not isinstance(value, str) or len(value) > max_length:
        raise SchemaValidationError(f"invalid {field_name}")
    if required and not value.strip():
        raise SchemaValidationError(f"invalid {field_name}")
    if any(unicodedata.category(char).startswith("C") for char in value):
        raise SchemaValidationError(f"invalid {field_name}")
    lowered = value.casefold()
    if any(marker in lowered for marker in SECRET_MARKERS):
        raise SchemaValidationError(f"unsafe {field_name}")
    return value.strip()


def _safe_id(value: Any, field_name: str) -> str:
    text = _safe_text(value, field_name, max_length=128)
    if _SAFE_ID.fullmatch(text) is None:
        raise SchemaValidationError(f"invalid {field_name}")
    return text


def _items(values: Sequence[Any] | None, field_name: str) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes)):
        raise SchemaValidationError(f"invalid {field_name}")
    result = tuple(_safe_text(value, field_name, max_length=256) for value in values)
    return tuple(dict.fromkeys(result))


def _fingerprint(value: Any) -> str:
    return replay_fingerprint(value)


@dataclass(frozen=True)
class EvidenceInput:
    evidence_id: str
    evidence_class: str
    state: str = "available"
    source_ref: str = "offline://consulting-engagement"
    summary: str = ""
    observed_at: str | None = None
    authoritative: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_id", _safe_id(self.evidence_id, "evidence_id"))
        object.__setattr__(self, "source_ref", _safe_text(self.source_ref, "source_ref", max_length=256))
        if self.evidence_class not in EVIDENCE_CLASSES:
            raise SchemaValidationError("invalid evidence class")
        if self.state not in EVIDENCE_STATES:
            raise SchemaValidationError("invalid evidence state")
        if self.summary:
            _safe_text(self.summary, "evidence summary")
        if self.observed_at is not None:
            _safe_text(self.observed_at, "observed_at", max_length=64)
        if not isinstance(self.authoritative, bool):
            raise SchemaValidationError("invalid evidence authority")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "EvidenceInput":
        if not isinstance(value, Mapping):
            raise SchemaValidationError("invalid evidence input")
        return cls(
            evidence_id=value.get("evidence_id", ""),
            evidence_class=value.get("evidence_class", "unavailable"),
            state=value.get("state", "available"),
            source_ref=value.get("source_ref", "offline://consulting-engagement"),
            summary=value.get("summary", ""),
            observed_at=value.get("observed_at"),
            authoritative=value.get("authoritative", False),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "evidence_class": self.evidence_class,
            "state": self.state,
            "source_ref": self.source_ref,
            "summary": self.summary,
            "observed_at": self.observed_at,
            "authoritative": self.authoritative,
        }

    def to_safe_dict(self) -> dict[str, Any]:
        return {"evidence_id": self.evidence_id, "evidence_class": self.evidence_class, "state": self.state}


@dataclass(frozen=True)
class ComponentReportReference:
    report_id: str
    service_name: str
    status: str
    workspace_id: str
    experiment_id: str

    def __post_init__(self) -> None:
        for field_name in ("report_id", "service_name", "status", "workspace_id", "experiment_id"):
            _safe_text(getattr(self, field_name), field_name, max_length=256)

    def to_dict(self) -> dict[str, str]:
        return {field_name: getattr(self, field_name) for field_name in self.__dataclass_fields__}


@dataclass(frozen=True)
class ExecutionPlanItem:
    deliverable: str
    service_name: str
    module_path: str
    function_name: str
    status: str
    reason: str | None = None
    read_only: bool = True
    dry_run: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {field_name: getattr(self, field_name) for field_name in self.__dataclass_fields__}


@dataclass(frozen=True)
class ConsultingEngagementRequest:
    client_id: str
    workspace_id: str
    client_objective: str
    geography: str
    language: str
    scope: str
    offering_kind: str
    selected_deliverables: tuple[str, ...] = ()
    evidence: tuple[EvidenceInput, ...] = ()
    assumptions: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    missing_information: tuple[str, ...] = ()
    linked_component_report_ids: tuple[str, ...] = ()
    optional_upsell_recommendations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "client_id", _safe_id(self.client_id, "client_id"))
        object.__setattr__(self, "workspace_id", _safe_id(self.workspace_id, "workspace_id"))
        for field_name in ("client_objective", "geography", "language", "scope"):
            object.__setattr__(self, field_name, _safe_text(getattr(self, field_name), field_name))
        if self.offering_kind not in OFFERING_KINDS:
            raise SchemaValidationError("invalid offering kind")
        deliverables = tuple(self.selected_deliverables)
        if any(item not in ALLOWED_DELIVERABLES for item in deliverables):
            raise SchemaValidationError("invalid selected deliverable")
        object.__setattr__(self, "selected_deliverables", tuple(dict.fromkeys(deliverables)))
        for item in self.evidence:
            if not isinstance(item, EvidenceInput):
                raise SchemaValidationError("invalid evidence input")
        object.__setattr__(self, "assumptions", _items(self.assumptions, "assumption"))
        object.__setattr__(self, "conflicts", _items(self.conflicts, "conflict"))
        object.__setattr__(self, "missing_information", _items(self.missing_information, "missing information"))
        upsells = _items(self.optional_upsell_recommendations, "upsell recommendation")
        if any(item not in OFFER_IDS for item in upsells):
            raise SchemaValidationError("optional_upsell_recommendations must reference the existing consulting_offers catalog")
        object.__setattr__(self, "optional_upsell_recommendations", upsells)
        object.__setattr__(self, "linked_component_report_ids", tuple(_safe_id(item, "component report id") for item in self.linked_component_report_ids))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ConsultingEngagementRequest":
        if not isinstance(value, Mapping):
            raise SchemaValidationError("engagement request must be an object")
        evidence = tuple(item if isinstance(item, EvidenceInput) else EvidenceInput.from_mapping(item) for item in value.get("evidence", ()))
        return cls(
            client_id=value.get("client_id", ""),
            workspace_id=value.get("workspace_id", ""),
            client_objective=value.get("client_objective", ""),
            geography=value.get("geography", ""),
            language=value.get("language", ""),
            scope=value.get("scope", ""),
            offering_kind=value.get("offering_kind", "unknown"),
            selected_deliverables=tuple(value.get("selected_deliverables", ())),
            evidence=evidence,
            assumptions=tuple(value.get("assumptions", ())),
            conflicts=tuple(value.get("conflicts", ())),
            missing_information=tuple(value.get("missing_information", ())),
            linked_component_report_ids=tuple(value.get("linked_component_report_ids", ())),
            optional_upsell_recommendations=tuple(value.get("optional_upsell_recommendations", ())),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "client_id": self.client_id,
            "workspace_id": self.workspace_id,
            "client_objective": self.client_objective,
            "geography": self.geography,
            "language": self.language,
            "scope": self.scope,
            "offering_kind": self.offering_kind,
            "selected_deliverables": list(self.selected_deliverables),
            "evidence": [item.to_dict() for item in self.evidence],
            "assumptions": list(self.assumptions),
            "conflicts": list(self.conflicts),
            "missing_information": list(self.missing_information),
            "linked_component_report_ids": list(self.linked_component_report_ids),
            "optional_upsell_recommendations": list(self.optional_upsell_recommendations),
        }

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.to_dict())


@dataclass(frozen=True)
class ConsultingEngagementResult:
    engagement_id: str
    client_id: str
    workspace_id: str
    client_objective: str
    geography: str
    language: str
    scope: str
    offering_kind: str
    selected_deliverables: tuple[str, ...]
    status: str
    evidence_summary: Mapping[str, Any]
    assumptions: tuple[str, ...]
    conflicts: tuple[str, ...]
    missing_information: tuple[str, ...]
    blockers: tuple[str, ...]
    next_action: str
    component_reports: tuple[ComponentReportReference, ...]
    execution_plan: tuple[ExecutionPlanItem, ...]
    client_safe_projection: Mapping[str, Any]
    trustos_export: Mapping[str, Any] | None
    fingerprint: str
    read_only: bool = True
    network_calls: bool = False
    database_writes: bool = False
    mutated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "engagement_id": self.engagement_id,
            "client_id": self.client_id,
            "workspace_id": self.workspace_id,
            "client_objective": self.client_objective,
            "geography": self.geography,
            "language": self.language,
            "scope": self.scope,
            "offering_kind": self.offering_kind,
            "selected_deliverables": list(self.selected_deliverables),
            "status": self.status,
            "evidence_summary": dict(self.evidence_summary),
            "assumptions": list(self.assumptions),
            "conflicts": list(self.conflicts),
            "missing_information": list(self.missing_information),
            "blockers": list(self.blockers),
            "next_action": self.next_action,
            "component_reports": [item.to_dict() for item in self.component_reports],
            "execution_plan": [item.to_dict() for item in self.execution_plan],
            "client_safe_projection": dict(self.client_safe_projection),
            "trustos_export": dict(self.trustos_export) if self.trustos_export else None,
            "fingerprint": self.fingerprint,
            "read_only": self.read_only,
            "network_calls": self.network_calls,
            "database_writes": self.database_writes,
            "mutated": self.mutated,
        }

    def to_markdown(self) -> str:
        return render_markdown_report(
            "MarketOS Consulting Engagement",
            [
                {
                    "heading": "Summary",
                    "body": {
                        "status": self.status,
                        "offering_kind": self.offering_kind,
                        "workspace_id": self.workspace_id,
                        "fingerprint": self.fingerprint,
                    },
                },
                {"heading": "Objective", "body": self.client_objective},
                {"heading": "Scope", "body": self.scope},
                {
                    "heading": "Evidence",
                    "body": {
                        "evidence_summary": dict(self.evidence_summary),
                        "assumptions": list(self.assumptions),
                        "missing_information": list(self.missing_information),
                    },
                },
                {
                    "heading": "Blockers and next action",
                    "body": {
                        "blockers": list(self.blockers) or ["None recorded."],
                        "next_action": self.next_action,
                    },
                },
            ],
            dry_run=True,
            generated_at=0.0,
        )
