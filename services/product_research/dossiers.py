"""Durable, provenance-first commerce research dossier contracts.

These contracts sit on top of the existing discovery/validation services. They
do not replace ``ResearchArtifact`` or ``ProductAuditResult``; they provide a
stable shape for the larger category-to-brand research report and preserve
source evidence needed for human approval.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


def _now() -> float:
    return time.time()


def _stable_id(kind: str, value: str) -> str:
    digest = hashlib.sha256(f"{kind}:{value.strip().lower()}".encode()).hexdigest()[:20]
    return f"{kind}_{digest}"


@dataclass(frozen=True)
class EvidenceRecord:
    source: str
    source_url: str = ""
    observed_at: float = field(default_factory=_now)
    retrieved_at: float = field(default_factory=_now)
    value: Mapping[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    quality: str = "unknown"
    cache_key: str = ""
    content_hash: str = ""
    status: str = "observed"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SupplierEvidence:
    supplier_id: str
    supplier_name: str
    product_id: str
    unit_cost: float | None = None
    shipping_cost: float | None = None
    shipping_days_min: int | None = None
    shipping_days_max: int | None = None
    inventory_units: int | None = None
    inventory_checked_at: float | None = None
    landed_cost: float | None = None
    currency: str = "USD"
    evidence: tuple[EvidenceRecord, ...] = ()
    validation_status: str = "unverified"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["evidence"] = [item.to_dict() for item in self.evidence]
        return data


@dataclass(frozen=True)
class ProductDossier:
    name: str
    category: str
    product_id: str = ""
    demand_evidence: tuple[EvidenceRecord, ...] = ()
    supplier_offers: tuple[SupplierEvidence, ...] = ()
    audience_hypotheses: tuple[Mapping[str, Any], ...] = ()
    competitor_evidence: tuple[EvidenceRecord, ...] = ()
    economics: Mapping[str, Any] = field(default_factory=dict)
    experiment_matrix: tuple[Mapping[str, Any], ...] = ()
    recommendation: str = "unreviewed"
    score: float = 0.0
    generated_at: float = field(default_factory=_now)

    def __post_init__(self) -> None:
        if not self.product_id:
            object.__setattr__(self, "product_id", _stable_id("product", f"{self.category}:{self.name}"))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["demand_evidence"] = [item.to_dict() for item in self.demand_evidence]
        data["competitor_evidence"] = [item.to_dict() for item in self.competitor_evidence]
        data["supplier_offers"] = [item.to_dict() for item in self.supplier_offers]
        return data


@dataclass(frozen=True)
class CategoryDossier:
    category: str
    products: tuple[ProductDossier, ...] = ()
    market_evidence: tuple[EvidenceRecord, ...] = ()
    audience_summary: Mapping[str, Any] = field(default_factory=dict)
    source_health: Mapping[str, Any] = field(default_factory=dict)
    portfolio: Mapping[str, Any] = field(default_factory=dict)
    scenarios: Mapping[str, Any] = field(default_factory=dict)
    tipping_point: Mapping[str, Any] = field(default_factory=dict)
    ollama_annotation: Mapping[str, Any] = field(default_factory=dict)
    status: str = "research_only"
    generated_at: float = field(default_factory=_now)

    @property
    def category_id(self) -> str:
        return _stable_id("category", self.category)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["products"] = [item.to_dict() for item in self.products]
        data["market_evidence"] = [item.to_dict() for item in self.market_evidence]
        data["category_id"] = self.category_id
        return data


@dataclass(frozen=True)
class BrandProposal:
    name: str
    category: str
    positioning: str
    product_ids: tuple[str, ...] = ()
    audience: Mapping[str, Any] = field(default_factory=dict)
    evidence_ids: tuple[str, ...] = ()
    scenarios: Mapping[str, Any] = field(default_factory=dict)
    tipping_point_score: float = 0.0
    approval_state: str = "not_requested"

    @property
    def brand_id(self) -> str:
        return _stable_id("brand", f"{self.category}:{self.name}")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["brand_id"] = self.brand_id
        return data


@dataclass(frozen=True)
class ApprovalRequest:
    subject_type: str
    subject_id: str
    requested_action: str
    state: str = "pending"
    requested_by: str = "marketos-research"
    decided_by: str = ""
    reason: str = ""
    created_at: float = field(default_factory=_now)
    decided_at: float | None = None

    def __post_init__(self) -> None:
        if self.subject_type not in {"brand", "inventory", "landing_page", "social_account", "ads"}:
            raise ValueError("unsupported approval subject type")
        if self.state not in {"pending", "approved", "rejected"}:
            raise ValueError("invalid approval state")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def content_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()
