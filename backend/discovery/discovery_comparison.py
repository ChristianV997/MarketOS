from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DiscoveryComparison:
    comparison_id: str
    workspace_id: str
    baseline_discovery_id: str
    current_discovery_id: str
    title: str
    summary: str
    category_movements: list[dict[str, Any]] = field(default_factory=list)
    new_categories: list[str] = field(default_factory=list)
    dropped_categories: list[str] = field(default_factory=list)
    confidence_changes: list[dict[str, Any]] = field(default_factory=list)
    evidence_count_change: int = 0
    recommendation_changes: list[dict[str, Any]] = field(default_factory=list)
    status: str = "completed"
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)
    def to_dict(self): return {key: getattr(self, key) for key in self.__dataclass_fields__}
    @classmethod
    def from_dict(cls, data): return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})
    def to_markdown(self):
        movements = "\n".join(f"- **{x['category_name']}**: rank {x.get('baseline_rank')} → {x.get('current_rank')}; score {x.get('baseline_score')} → {x.get('current_score')}" for x in self.category_movements) or "- None."
        return f"# {self.title}\n\n{self.summary}\n\nBaseline: `{self.baseline_discovery_id}`  \nCurrent: `{self.current_discovery_id}`  \nEvidence count change: `{self.evidence_count_change}`\n\n## Category movements\n\n{movements}\n\n## New categories\n\n{', '.join(self.new_categories) or 'None'}\n\n## Dropped categories\n\n{', '.join(self.dropped_categories) or 'None'}\n\n## Interpretation\n\nA score change means the recorded scoring output changed after the compared evidence set; it does not establish causality or prove that a market improved.\n"


def compare_category_discoveries(baseline, current, workspace_id: str = "default") -> DiscoveryComparison:
    before = {item.category_name: item for item in (baseline.category_opportunities if baseline else [])}; after = {item.category_name: item for item in (current.category_opportunities if current else [])}
    names = sorted(set(before) | set(after)); movements = []; recommendation_changes = []
    for name in names:
        old, new = before.get(name), after.get(name)
        if old and new:
            movement = {"category_name": name, "baseline_rank": old.rank, "current_rank": new.rank, "rank_change": old.rank - new.rank, "baseline_score": old.score, "current_score": new.score, "score_change": round(new.score - old.score, 4)}; movements.append(movement)
            if old.recommendation != new.recommendation: recommendation_changes.append({"category_name": name, "baseline": old.recommendation, "current": new.recommendation})
    new_categories = sorted(set(after) - set(before)); dropped = sorted(set(before) - set(after))
    summary = "Compared recorded category scores and ranks; changes are descriptive and not causal."
    return DiscoveryComparison("comparison_" + uuid.uuid4().hex[:16], workspace_id, baseline.discovery_id if baseline else "", current.discovery_id if current else "", "Discovery Run Comparison", summary, movements, new_categories, dropped, [{"category_name": x["category_name"], "score_change": x["score_change"]} for x in movements if x["score_change"]], (current.evidence_count if current else 0) - (baseline.evidence_count if baseline else 0), recommendation_changes, metadata={"supported_facts_only": True})
