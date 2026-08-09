from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .evidence_source_contract import EvidenceRecord


@dataclass
class CategoryOpportunity:
    category_id: str
    category_name: str
    score: float
    rank: int
    recommendation: str
    evidence_ids: list[str] = field(default_factory=list)
    signal_summary: dict[str, Any] = field(default_factory=dict)
    risk_flags: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    def to_dict(self) -> dict[str, Any]: return {key: getattr(self, key) for key in self.__dataclass_fields__}
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CategoryOpportunity": return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})


@dataclass
class CategoryDiscoveryRun:
    discovery_id: str
    workspace_id: str
    title: str
    objective: str
    source_names: list[str] = field(default_factory=list)
    status: str = "created"
    category_opportunities: list[CategoryOpportunity] = field(default_factory=list)
    evidence_count: int = 0
    blocked_reasons: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    def to_dict(self) -> dict[str, Any]: return {key: [item.to_dict() for item in value] if key == "category_opportunities" else value for key, value in ((key, getattr(self, key)) for key in self.__dataclass_fields__)}
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CategoryDiscoveryRun":
        data = dict(data); data["category_opportunities"] = [CategoryOpportunity.from_dict(item) for item in data.get("category_opportunities", [])]; return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})
    def to_markdown(self) -> str:
        rows = "\n".join(f"{item.rank}. **{item.category_name}** — {item.score:.2f}/100 — `{item.recommendation}`; missing: {', '.join(item.missing_evidence) or 'none'}" for item in self.category_opportunities) or "No category opportunities were produced."
        return f"# {self.title}\n\n**Status:** `{self.status}`  \n**Objective:** {self.objective}\n\nEvidence sources: {', '.join(self.source_names) or 'none'}  \nEvidence records: {self.evidence_count}\n\n## Ranked categories\n\n{rows}\n\n## Provenance\n\nThis report contains only supplied evidence; it does not claim real market demand.\n"


def discover_categories_from_evidence(evidence_records: list[EvidenceRecord], workspace_id: str = "default", title: str = "Market Category Discovery", objective: str = "Identify promising product categories") -> CategoryDiscoveryRun:
    groups: dict[str, list[EvidenceRecord]] = {}
    for record in evidence_records:
        if record.entity_type in {"category", "product_theme", "keyword"} and record.entity_name:
            groups.setdefault(record.entity_name.strip().lower(), []).append(record)
    opportunities: list[CategoryOpportunity] = []
    for name, records in groups.items():
        signal: dict[str, list[float]] = {}; risks: list[str] = []; provenance_types = set()
        for record in records:
            try: value = max(0.0, min(float(record.value), 1.0))
            except (TypeError, ValueError): continue
            signal.setdefault(record.signal_type, []).append(value * record.weight * record.confidence); provenance_types.update(str(value) for value in record.provenance.values() if isinstance(value, (str, bool)))
        def avg(key: str) -> float: return sum(signal.get(key, [])) / len(signal[key]) if signal.get(key) else 0.0
        positive = 0.25 * avg("demand_proxy") + 0.20 * avg("trend_proxy") + 0.15 * avg("margin_proxy") + 0.10 * avg("audience_proxy") + 0.10 * avg("creative_proxy")
        penalty = 0.15 * avg("competition_proxy") + 0.10 * avg("risk_proxy")
        score = round(max(0.0, min(100.0, (positive + min(len(signal), 5) * 0.04 - penalty) * 100)), 2)
        missing = [key for key in ("demand_proxy", "trend_proxy", "margin_proxy", "competition_proxy") if not signal.get(key)]
        if avg("risk_proxy") >= 0.6: risks.append("high_risk_proxy")
        risks.extend(f"missing_{key}" for key in missing)
        recommendation = "prioritize" if score >= 65 and not risks else "investigate" if score >= 40 else "hold" if score >= 20 else "reject"
        category_id = f"category_{uuid.uuid5(uuid.NAMESPACE_URL, name).hex[:16]}"
        opportunities.append(CategoryOpportunity(category_id, name, score, 0, recommendation, [r.evidence_id for r in records], {key: round(avg(key), 4) for key in signal}, sorted(set(risks)), missing, {"provenance_values": sorted(provenance_types), "evidence_count": len(records)}, {"synthetic_or_cached_only": any(r.provenance.get("not_real_market_data") is True for r in records)}))
    opportunities.sort(key=lambda item: (-item.score, item.category_name))
    for index, item in enumerate(opportunities, 1): item.rank = index
    run_status = "completed" if opportunities else "blocked"
    return CategoryDiscoveryRun(f"discovery_{uuid.uuid4().hex[:16]}", workspace_id, title, objective, sorted({r.source_name for r in evidence_records}), run_status, opportunities, len(evidence_records), [] if opportunities else ["no_valid_category_evidence"], finished_at=time.time(), metadata={"method": "deterministic_evidence_scoring", "real_market_claims": False})
