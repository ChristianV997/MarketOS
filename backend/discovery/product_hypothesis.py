from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .category_discovery import CategoryDiscoveryRun
from .evidence_source_contract import EvidenceRecord


@dataclass
class ProductHypothesis:
    hypothesis_id: str
    category_id: str
    category_name: str
    product_name: str
    product_theme: str
    target_audience: str
    price_band: str
    evidence_ids: list[str] = field(default_factory=list)
    rationale: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    confidence: float = 0.0
    provenance: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    def to_dict(self) -> dict[str, Any]: return {key: getattr(self, key) for key in self.__dataclass_fields__}
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProductHypothesis": return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})


@dataclass
class ProductHypothesisRun:
    hypothesis_run_id: str
    discovery_id: str
    workspace_id: str
    hypotheses: list[ProductHypothesis] = field(default_factory=list)
    status: str = "completed"
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)
    def to_dict(self) -> dict[str, Any]: return {key: [item.to_dict() for item in value] if key == "hypotheses" else value for key, value in ((key, getattr(self, key)) for key in self.__dataclass_fields__)}
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProductHypothesisRun":
        data = dict(data); data["hypotheses"] = [ProductHypothesis.from_dict(item) for item in data.get("hypotheses", [])]; return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})
    def to_markdown(self) -> str:
        rows = "\n".join(f"- **{item.product_name}** ({item.category_name}) — confidence {item.confidence:.2f}; missing: {', '.join(item.missing_evidence) or 'none'}" for item in self.hypotheses) or "- No hypotheses produced."
        return f"# Product hypotheses\n\n**Status:** `{self.status}`\n\n{rows}\n\nThese are hypotheses only; no existence, demand, sales, or profitability claim is made.\n"


def generate_product_hypotheses(discovery_run: CategoryDiscoveryRun, evidence_records: list[EvidenceRecord], max_per_category: int = 3, max_total: int = 20) -> ProductHypothesisRun:
    max_per_category, max_total = max(0, int(max_per_category)), max(0, int(max_total))
    records_by_name: dict[str, list[EvidenceRecord]] = {}
    for record in evidence_records: records_by_name.setdefault(record.entity_name.strip().lower(), []).append(record)
    hypotheses: list[ProductHypothesis] = []
    for category in discovery_run.category_opportunities:
        if category.recommendation == "reject" and len(hypotheses) < max_total: continue
        records = records_by_name.get(category.category_name.lower(), [])
        themes = [r for r in evidence_records if r.entity_type in {"product_theme", "keyword"} and (r.entity_name.lower() == category.category_name.lower() or r.metadata.get("category", "").lower() == category.category_name.lower())]
        if not themes: themes = records[:max_per_category]
        if not themes: themes = [None]
        for index, theme_record in enumerate(themes[:max_per_category]):
            theme = str(theme_record.value if theme_record is not None else "opportunity theme")
            product_name = f"{category.category_name} {theme}".strip() if theme != "opportunity theme" else f"{category.category_name} opportunity theme"
            evidence_ids = category.evidence_ids + ([theme_record.evidence_id] if theme_record is not None else [])
            hypotheses.append(ProductHypothesis(f"hypothesis_{uuid.uuid5(uuid.NAMESPACE_URL, category.category_id + ':' + product_name).hex[:16]}", category.category_id, category.category_name, product_name, theme, "Audience hypothesis requires validation", "unknown", sorted(set(evidence_ids)), [f"Derived from ranked category score {category.score:.2f}.", "Product identity and demand remain unverified."], sorted(set(category.risk_flags + ["product_not_validated"])), sorted(set(category.missing_evidence + ["product_level_demand", "supplier_offer", "shipping_time"])), round(min(1.0, category.score / 100 * 0.7), 4), {"method": "deterministic_category_to_hypothesis", "source_provenance": category.provenance}, {"synthetic_or_cached_only": True}))
            if len(hypotheses) >= max_total: break
        if len(hypotheses) >= max_total: break
    return ProductHypothesisRun(f"hypotheses_{uuid.uuid4().hex[:16]}", discovery_run.discovery_id, discovery_run.workspace_id, hypotheses[:max_total], "completed" if hypotheses else "blocked", metadata={"real_market_claims": False})
