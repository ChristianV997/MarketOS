"""Typed, safe contracts for the consulting-offer composition boundary."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

from evaluation.commerce.kernel_integration import replay_fingerprint
from evaluation.secret_markers import contains_boundary_prefixed_sk_token

OFFER_IDS = (
    "diagnostic-audit",
    "market-research-sprint",
    "unit-service-economics",
    "supplier-logistics-feasibility",
    "marketing-publicity-strategy",
    "full-commercial-assessment",
)
OFFERING_KINDS = frozenset({"product", "service", "hybrid", "unknown"})
EVIDENCE_CLASSES = frozenset({
    "fixture", "manual", "manual_import", "observed", "derived", "simulated",
    "planned", "live", "actual_executed", "unavailable",
})
EVIDENCE_STATES = frozenset({"available", "missing", "stale", "conflicting", "blocked", "unavailable"})
PROPOSAL_STATUSES = frozenset({"draft_ready", "needs_evidence", "blocked"})
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SECRET_MARKERS = (
    "ghp_", "github_pat_", "bearer ", "-----begin", "api_key", "access_token",
    "private_key", "password", "client_secret", "cookie=", "raw_payload", "source_code",
    "internal_prompt", "formula", ".env",
)



class SchemaValidationError(ValueError):
    """Stable validation error that never reflects attacker-controlled values."""


def _safe_text(value: Any, field_name: str, *, required: bool = True, max_length: int = 512) -> str:
    if not isinstance(value, str) or len(value) > max_length:
        raise SchemaValidationError(f"invalid {field_name}")
    if required and not value.strip():
        raise SchemaValidationError(f"invalid {field_name}")
    if any(unicodedata.category(char).startswith("C") for char in value):
        raise SchemaValidationError(f"invalid {field_name}")
    lowered = value.casefold()
    if contains_boundary_prefixed_sk_token(value) or any(marker in lowered for marker in _SECRET_MARKERS):
        raise SchemaValidationError(f"unsafe {field_name}")
    return value.strip()


def _safe_id(value: Any, field_name: str) -> str:
    text = _safe_text(value, field_name, max_length=128)
    if _SAFE_ID.fullmatch(text) is None:
        raise SchemaValidationError(f"invalid {field_name}")
    return text


def _items(values: Sequence[Any] | None, field_name: str, *, max_length: int = 256) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes)):
        raise SchemaValidationError(f"invalid {field_name}")
    return tuple(dict.fromkeys(_safe_text(value, field_name, max_length=max_length) for value in values))


def _decimal(value: Any, field_name: str, *, nonnegative: bool = False) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise SchemaValidationError(f"invalid {field_name}") from None
    if not result.is_finite() or (nonnegative and result < 0):
        raise SchemaValidationError(f"invalid {field_name}")
    return result


@dataclass(frozen=True)
class EvidenceInput:
    evidence_id: str
    evidence_class: str
    state: str = "available"
    source_ref: str = "offline://consulting-offers"
    summary: str = ""
    authoritative: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_id", _safe_id(self.evidence_id, "evidence_id"))
        object.__setattr__(self, "source_ref", _safe_text(self.source_ref, "source_ref", max_length=256))
        if self.evidence_class not in EVIDENCE_CLASSES:
            raise SchemaValidationError("invalid evidence class")
        if self.state not in EVIDENCE_STATES:
            raise SchemaValidationError("invalid evidence state")
        if self.summary:
            _safe_text(self.summary, "evidence summary", max_length=512)
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
            source_ref=value.get("source_ref", "offline://consulting-offers"),
            summary=value.get("summary", ""),
            authoritative=value.get("authoritative", False),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "evidence_class": self.evidence_class,
            "state": self.state,
            "source_ref": self.source_ref,
            "summary": self.summary,
            "authoritative": self.authoritative,
        }

    def to_safe_dict(self) -> dict[str, str]:
        return {"evidence_id": self.evidence_id, "evidence_class": self.evidence_class, "state": self.state}


@dataclass(frozen=True)
class ComponentReportReference:
    report_id: str
    service_name: str
    status: str
    workspace_id: str
    experiment_id: str

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            _safe_text(getattr(self, field_name), field_name, max_length=256)

    def to_dict(self) -> dict[str, str]:
        return {field_name: getattr(self, field_name) for field_name in self.__dataclass_fields__}


@dataclass(frozen=True)
class PlanningPriceRange:
    currency: str
    minimum: Decimal
    maximum: Decimal
    source_package_ids: tuple[str, ...]
    evidence_state: str = "assumed"
    note: str = "Planning band only; final price requires client scope review."

    def __post_init__(self) -> None:
        currency = _safe_text(self.currency, "currency", max_length=3).upper()
        if currency not in {"CAD", "EUR", "GBP", "MXN", "USD"}:
            raise SchemaValidationError("invalid currency")
        object.__setattr__(self, "currency", currency)
        minimum = _decimal(self.minimum, "price minimum", nonnegative=True)
        maximum = _decimal(self.maximum, "price maximum", nonnegative=True)
        if maximum < minimum:
            raise SchemaValidationError("invalid price range")
        object.__setattr__(self, "minimum", minimum)
        object.__setattr__(self, "maximum", maximum)
        object.__setattr__(self, "source_package_ids", tuple(_safe_id(item, "source package id") for item in self.source_package_ids))
        if self.evidence_state != "assumed":
            raise SchemaValidationError("planning price must remain assumed")
        object.__setattr__(self, "note", _safe_text(self.note, "price note", max_length=256))

    def to_dict(self) -> dict[str, Any]:
        return {
            "currency": self.currency,
            "minimum": str(self.minimum),
            "maximum": str(self.maximum),
            "source_package_ids": list(self.source_package_ids),
            "evidence_state": self.evidence_state,
            "note": self.note,
        }


@dataclass(frozen=True)
class OfferDefinition:
    offer_id: str
    name: str
    summary: str
    supported_offering_kinds: tuple[str, ...]
    source_package_ids: tuple[str, ...]
    component_services: tuple[str, ...]
    required_inputs: tuple[str, ...]
    evidence_requirements: tuple[str, ...]
    deliverables: tuple[str, ...]
    exclusions: tuple[str, ...]
    assumptions: tuple[str, ...]
    human_review_points: tuple[str, ...]
    turnaround_days: int
    upgrade_offer_ids: tuple[str, ...]
    price_range: PlanningPriceRange

    def __post_init__(self) -> None:
        object.__setattr__(self, "offer_id", _safe_id(self.offer_id, "offer id"))
        for field_name in ("name", "summary"):
            object.__setattr__(self, field_name, _safe_text(getattr(self, field_name), field_name))
        kinds = tuple(dict.fromkeys(self.supported_offering_kinds))
        if not kinds or any(item not in OFFERING_KINDS for item in kinds):
            raise SchemaValidationError("invalid supported offering kinds")
        object.__setattr__(self, "supported_offering_kinds", kinds)
        for field_name in ("source_package_ids", "component_services", "required_inputs", "evidence_requirements", "deliverables", "exclusions", "assumptions", "human_review_points", "upgrade_offer_ids"):
            object.__setattr__(self, field_name, _items(getattr(self, field_name), field_name))
        if not isinstance(self.turnaround_days, int) or isinstance(self.turnaround_days, bool) or not 1 <= self.turnaround_days <= 365:
            raise SchemaValidationError("invalid turnaround")
        if self.price_range.source_package_ids != self.source_package_ids:
            raise SchemaValidationError("price source mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {
            "offer_id": self.offer_id,
            "name": self.name,
            "summary": self.summary,
            "supported_offering_kinds": list(self.supported_offering_kinds),
            "source_package_ids": list(self.source_package_ids),
            "component_services": list(self.component_services),
            "required_inputs": list(self.required_inputs),
            "evidence_requirements": list(self.evidence_requirements),
            "deliverables": list(self.deliverables),
            "exclusions": list(self.exclusions),
            "assumptions": list(self.assumptions),
            "human_review_points": list(self.human_review_points),
            "turnaround_days": self.turnaround_days,
            "upgrade_offer_ids": list(self.upgrade_offer_ids),
            "price_range": self.price_range.to_dict(),
        }


@dataclass(frozen=True)
class ConsultingOfferRequest:
    client_id: str
    workspace_id: str
    client_objective: str
    geography: str
    language: str
    scope: str
    offering_kind: str
    selected_offer_ids: tuple[str, ...]
    pricing_currency: str = "USD"
    evidence: tuple[EvidenceInput, ...] = ()
    assumptions: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    missing_information: tuple[str, ...] = ()
    linked_component_report_ids: tuple[str, ...] = ()
    consulting_engagement_id: str | None = None
    optional_upsell_offer_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "client_id", _safe_id(self.client_id, "client id"))
        object.__setattr__(self, "workspace_id", _safe_id(self.workspace_id, "workspace id"))
        for field_name in ("client_objective", "geography", "language", "scope"):
            object.__setattr__(self, field_name, _safe_text(getattr(self, field_name), field_name))
        if self.offering_kind not in OFFERING_KINDS:
            raise SchemaValidationError("invalid offering kind")
        selected = tuple(dict.fromkeys(_safe_id(item, "offer id") for item in self.selected_offer_ids))
        if not selected or any(item not in OFFER_IDS for item in selected):
            raise SchemaValidationError("invalid selected offer")
        object.__setattr__(self, "selected_offer_ids", selected)
        currency = _safe_text(self.pricing_currency, "pricing currency", max_length=3).upper()
        if currency not in {"CAD", "EUR", "GBP", "MXN", "USD"}:
            raise SchemaValidationError("invalid pricing currency")
        object.__setattr__(self, "pricing_currency", currency)
        if any(not isinstance(item, EvidenceInput) for item in self.evidence):
            raise SchemaValidationError("invalid evidence input")
        object.__setattr__(self, "assumptions", _items(self.assumptions, "assumption"))
        object.__setattr__(self, "conflicts", _items(self.conflicts, "conflict"))
        object.__setattr__(self, "missing_information", _items(self.missing_information, "missing information"))
        object.__setattr__(self, "linked_component_report_ids", tuple(_safe_id(item, "component report id") for item in self.linked_component_report_ids))
        upsells = tuple(_safe_id(item, "upsell offer id") for item in self.optional_upsell_offer_ids)
        if any(item not in OFFER_IDS for item in upsells):
            raise SchemaValidationError("invalid upsell offer")
        object.__setattr__(self, "optional_upsell_offer_ids", upsells)
        if self.consulting_engagement_id is not None:
            object.__setattr__(self, "consulting_engagement_id", _safe_id(self.consulting_engagement_id, "consulting engagement id"))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ConsultingOfferRequest":
        if not isinstance(value, Mapping):
            raise SchemaValidationError("offer request must be an object")
        evidence = tuple(item if isinstance(item, EvidenceInput) else EvidenceInput.from_mapping(item) for item in value.get("evidence", ()))
        return cls(
            client_id=value.get("client_id", ""), workspace_id=value.get("workspace_id", ""),
            client_objective=value.get("client_objective", ""), geography=value.get("geography", ""),
            language=value.get("language", ""), scope=value.get("scope", ""),
            offering_kind=value.get("offering_kind", "unknown"),
            selected_offer_ids=tuple(value.get("selected_offer_ids", ())),
            pricing_currency=value.get("pricing_currency", "USD"), evidence=evidence,
            assumptions=tuple(value.get("assumptions", ())), conflicts=tuple(value.get("conflicts", ())),
            missing_information=tuple(value.get("missing_information", ())),
            linked_component_report_ids=tuple(value.get("linked_component_report_ids", ())),
            consulting_engagement_id=value.get("consulting_engagement_id"),
            optional_upsell_offer_ids=tuple(value.get("optional_upsell_offer_ids", ())),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "client_id": self.client_id, "workspace_id": self.workspace_id,
            "client_objective": self.client_objective, "geography": self.geography,
            "language": self.language, "scope": self.scope, "offering_kind": self.offering_kind,
            "selected_offer_ids": list(self.selected_offer_ids), "pricing_currency": self.pricing_currency,
            "evidence": [item.to_dict() for item in self.evidence],
            "assumptions": list(self.assumptions), "conflicts": list(self.conflicts),
            "missing_information": list(self.missing_information),
            "linked_component_report_ids": list(self.linked_component_report_ids),
            "consulting_engagement_id": self.consulting_engagement_id,
            "optional_upsell_offer_ids": list(self.optional_upsell_offer_ids),
        }

    @property
    def fingerprint(self) -> str:
        return replay_fingerprint(self.to_dict())


@dataclass(frozen=True)
class ConsultingOfferProposal:
    proposal_id: str
    client_id: str
    workspace_id: str
    offering_kind: str
    selected_offers: tuple[OfferDefinition, ...]
    status: str
    price_ranges: tuple[PlanningPriceRange, ...]
    evidence_summary: Mapping[str, Any]
    component_reports: tuple[ComponentReportReference, ...]
    proposal_draft: Mapping[str, Any]
    sow_draft: Mapping[str, Any]
    client_safe_projection: Mapping[str, Any]
    trustos_export: Mapping[str, Any]
    blockers: tuple[str, ...]
    next_action: str
    fingerprint: str
    read_only: bool = True
    live_actions_taken: bool = False
    database_writes: bool = False

    def __post_init__(self) -> None:
        if self.status not in PROPOSAL_STATUSES:
            raise SchemaValidationError("invalid proposal status")
        if not self.read_only or self.live_actions_taken or self.database_writes:
            raise SchemaValidationError("unsafe proposal mode")

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id, "client_id": self.client_id, "workspace_id": self.workspace_id,
            "offering_kind": self.offering_kind, "selected_offers": [item.to_dict() for item in self.selected_offers],
            "status": self.status, "price_ranges": [item.to_dict() for item in self.price_ranges],
            "evidence_summary": dict(self.evidence_summary), "component_reports": [item.to_dict() for item in self.component_reports],
            "proposal_draft": dict(self.proposal_draft), "sow_draft": dict(self.sow_draft),
            "client_safe_projection": dict(self.client_safe_projection), "trustos_export": dict(self.trustos_export),
            "blockers": list(self.blockers), "next_action": self.next_action, "fingerprint": self.fingerprint,
            "read_only": self.read_only, "live_actions_taken": self.live_actions_taken, "database_writes": self.database_writes,
        }

    def to_markdown(self) -> str:
        from services.reporting.render import render_markdown_report
        return render_markdown_report(
            "MarketOS Consulting Offer Proposal",
            [
                {"heading": "Status", "body": {"status": self.status, "offering_kind": self.offering_kind, "fingerprint": self.fingerprint}},
                {"heading": "Offers", "body": [{"offer_id": item.offer_id, "name": item.name, "price_range": item.price_range.to_dict()} for item in self.selected_offers]},
                {"heading": "Proposal Draft", "body": dict(self.proposal_draft)},
                {"heading": "Statement of Work Draft", "body": dict(self.sow_draft)},
                {"heading": "Blockers and Next Action", "body": {"blockers": list(self.blockers) or ["None recorded."], "next_action": self.next_action}},
            ],
            dry_run=True,
            generated_at=0.0,
        )
