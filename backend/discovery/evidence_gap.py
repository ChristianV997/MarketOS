from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .discovery_registry import get_discovery_registry
from .import_registry import get_import_registry


@dataclass
class EvidenceGap:
    gap_id: str
    workspace_id: str
    entity_type: str
    entity_name: str
    category_name: str
    missing_signal_type: str
    severity: str
    priority_score: float
    rationale: list[str] = field(default_factory=list)
    recommended_parser_types: list[str] = field(default_factory=list)
    recommended_source_types: list[str] = field(default_factory=list)
    required_fields: list[str] = field(default_factory=list)
    related_evidence_ids: list[str] = field(default_factory=list)
    related_report_ids: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None: self.priority_score = max(0.0, min(float(self.priority_score), 100.0))
    def to_dict(self) -> dict[str, Any]: return {key: getattr(self, key) for key in self.__dataclass_fields__}
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidenceGap": return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})


@dataclass
class EvidenceGapAnalysis:
    analysis_id: str
    workspace_id: str
    title: str
    objective: str
    gaps: list[EvidenceGap] = field(default_factory=list)
    strongest_categories: list[dict[str, Any]] = field(default_factory=list)
    weakest_categories: list[dict[str, Any]] = field(default_factory=list)
    evidence_coverage: dict[str, Any] = field(default_factory=dict)
    recommended_next_imports: list[dict[str, Any]] = field(default_factory=list)
    status: str = "completed"
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]: return {key: [item.to_dict() for item in value] if key == "gaps" else value for key, value in ((key, getattr(self, key)) for key in self.__dataclass_fields__)}
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidenceGapAnalysis":
        data = dict(data); data["gaps"] = [EvidenceGap.from_dict(item) for item in data.get("gaps", [])]; return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})
    def to_markdown(self) -> str:
        gaps = "\n".join(f"- **{gap.entity_name}** / `{gap.missing_signal_type}` — `{gap.severity}`, priority `{gap.priority_score:.1f}`; import: {', '.join(gap.recommended_parser_types)}" for gap in self.gaps) or "- No material gaps identified from available evidence."
        strongest = ", ".join(str(item.get("category_name", "")) for item in self.strongest_categories) or "None"
        weakest = ", ".join(str(item.get("category_name", "")) for item in self.weakest_categories) or "None"
        return f"# {self.title}\n\n**Status:** `{self.status}`  \n**Objective:** {self.objective}\n\n## Evidence coverage\n\n```json\n{self.evidence_coverage}\n```\n\n**Strongest recorded categories:** {strongest}  \n**Weakest recorded categories:** {weakest}\n\n## Prioritized evidence gaps\n\n{gaps}\n\n## Interpretation\n\nThese are missing-evidence findings, not claims about market demand or profitability. Synthetic or local-only evidence remains explicitly limited.\n"


_GAP_MAP = {
    "demand_proxy": ("high", ["google_trends_csv", "amazon_bestsellers_csv", "mercadolibre_snapshot_csv"], ["trend_proxy", "demand_proxy"], ["category", "keyword", "trend_score", "growth", "region"]),
    "trend_proxy": ("high", ["google_trends_csv", "tiktok_creative_center_csv"], ["trend_proxy"], ["category", "keyword", "trend_score", "growth"]),
    "competition_proxy": ("high", ["meta_ad_library_csv", "amazon_bestsellers_csv", "mercadolibre_snapshot_csv"], ["competition_proxy"], ["category", "product", "ad_count", "active_days", "seller_count"]),
    "margin_proxy": ("critical", ["supplier_catalog_csv"], ["margin_proxy", "supplier_proxy", "risk_proxy"], ["category", "product", "supplier_cost", "shipping_cost", "moq", "lead_time_days", "availability", "supplier"]),
    "supplier_proxy": ("high", ["supplier_catalog_csv"], ["supplier_proxy", "risk_proxy"], ["category", "product", "supplier", "availability", "lead_time_days"]),
    "price_signal": ("medium", ["amazon_bestsellers_csv", "mercadolibre_snapshot_csv", "supplier_catalog_csv"], ["price_signal"], ["category", "product", "price", "supplier_cost", "shipping_cost"]),
    "audience_proxy": ("medium", ["reddit_keyword_csv"], ["audience_proxy", "pain_point"], ["subreddit", "keyword", "category", "mentions", "upvotes", "comments", "pain_point"]),
    "creative_proxy": ("medium", ["tiktok_creative_center_csv", "meta_ad_library_csv"], ["creative_proxy", "trend_proxy"], ["category", "product", "views", "likes", "ctr", "ad_count", "active_days"]),
}


def analyze_evidence_gaps(workspace_id: str = "default", discovery_id: str | None = None, hypothesis_run_id: str | None = None, top_n: int = 10) -> EvidenceGapAnalysis:
    registry = get_discovery_registry(); records = registry.list_evidence(workspace_id=workspace_id, limit=10000)
    runs = registry.list_category_discoveries(workspace_id=workspace_id, limit=500)
    discovery = registry.get_category_discovery(discovery_id) if discovery_id else (runs[0] if runs else None)
    opportunities = discovery.category_opportunities if discovery else []
    signal_by_entity: dict[str, set[str]] = {}
    evidence_by_entity: dict[str, list[str]] = {}
    for record in records:
        name = record.entity_name.strip().lower()
        signal_by_entity.setdefault(name, set()).add(record.signal_type)
        evidence_by_entity.setdefault(name, []).append(record.evidence_id)
    gaps: list[EvidenceGap] = []
    categories = opportunities or [{"category_name": "initial market discovery", "score": 0, "recommendation": "investigate"}]
    for item in categories:
        name = item.category_name if hasattr(item, "category_name") else str(item.get("category_name"))
        score = float(item.score if hasattr(item, "score") else item.get("score", 0))
        observed = signal_by_entity.get(name.lower(), set())
        for signal, (severity, parsers, allowed, fields) in _GAP_MAP.items():
            if signal in observed: continue
            priority = (100.0 if severity == "critical" else 80.0 if severity == "high" else 55.0) + max(0.0, 30.0 - score * 0.3)
            provenance_warning = any(record.provenance.get("not_real_market_data") is True for record in records if record.entity_name.strip().lower() == name.lower())
            rationale = [f"No `{signal}` evidence is recorded for this category."]
            if provenance_warning: rationale.append("Existing evidence is synthetic and needs a real or user-provided cached export.")
            gap_id = f"gap_{uuid.uuid5(uuid.NAMESPACE_URL, f'{workspace_id}:{name}:{signal}').hex[:16]}"
            gaps.append(EvidenceGap(gap_id, workspace_id, "category", name, name, signal, severity, priority, rationale, parsers, ["local_file", "fixture"], fields, evidence_by_entity.get(name.lower(), []), [], {"method": "persisted_evidence_gap_analysis", "real_market_claims": False}, {"observed_signals": sorted(observed), "synthetic_only": provenance_warning}))
    gaps.sort(key=lambda gap: (-gap.priority_score, gap.entity_name, gap.missing_signal_type))
    gaps = gaps[:max(1, min(int(top_n), 100))]
    category_dicts = [item.to_dict() if hasattr(item, "to_dict") else item for item in opportunities]
    strongest = sorted(category_dicts, key=lambda item: (-float(item.get("score", 0)), item.get("category_name", "")))[:5]
    weakest = sorted(category_dicts, key=lambda item: (float(item.get("score", 0)), item.get("category_name", "")))[:5]
    coverage = {"evidence_count": len(records), "category_count": len(opportunities), "signal_types": sorted({record.signal_type for record in records}), "synthetic_only": bool(records) and all(record.provenance.get("not_real_market_data") is True for record in records)}
    return EvidenceGapAnalysis("gap_analysis_" + uuid.uuid4().hex[:16], workspace_id, "Evidence Gap Analysis", "Identify the next evidence needed to improve category and product confidence", gaps, strongest, weakest, coverage, [], "completed", metadata={"discovery_id": discovery.discovery_id if discovery else None, "hypothesis_run_id": hypothesis_run_id, "real_market_claims": False})
