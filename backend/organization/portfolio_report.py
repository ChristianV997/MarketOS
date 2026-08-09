from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PortfolioReport:
    portfolio_report_id: str
    workspace_id: str
    title: str
    summary: str
    report_ids: list[str] = field(default_factory=list)
    service_counts: dict[str, int] = field(default_factory=dict)
    status_counts: dict[str, int] = field(default_factory=dict)
    top_recommendations: list[str] = field(default_factory=list)
    recurring_risk_flags: list[dict[str, Any]] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]: return {key: getattr(self, key) for key in self.__dataclass_fields__}
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PortfolioReport": return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})
    def to_markdown(self) -> str:
        counts = lambda values: "\n".join(f"- `{key}`: {value}" for key, value in sorted(values.items())) or "- None."
        risks = "\n".join(f"- `{item.get('flag')}`: {item.get('count')}" for item in self.recurring_risk_flags) or "- None."
        bullets = lambda values: "\n".join(f"- {value}" for value in values) or "- None."
        return f"# {self.title}\n\n**Status:** `{self.metadata.get('status', 'completed')}`  \n**Workspace:** `{self.workspace_id}`  \n**Portfolio report ID:** `{self.portfolio_report_id}`\n\n## Summary\n\n{self.summary}\n\n## Service counts\n\n{counts(self.service_counts)}\n\n## Status counts\n\n{counts(self.status_counts)}\n\n## Recurring risk flags\n\n{risks}\n\n## Top recommendations\n\n{bullets(self.top_recommendations)}\n\n## Next actions\n\n{bullets(self.next_actions)}\n\n## Linked report IDs\n\n{bullets(self.report_ids)}\n\n## Metrics\n\n```json\n{json.dumps(self.metrics, indent=2, default=str)}\n```\n"


def build_portfolio_report(workspace_id: str, reports: list, title: str | None = None, limit_recommendations: int = 10) -> PortfolioReport:
    reports = list(reports or [])
    report_ids = sorted({report.report_id for report in reports})
    service_counts: dict[str, int] = {}; status_counts: dict[str, int] = {}; recommendation_counts: dict[str, int] = {}; next_action_counts: dict[str, int] = {}; risk_counts: dict[str, int] = {}
    for report in reports:
        service_counts[report.service_name] = service_counts.get(report.service_name, 0) + 1
        status_counts[report.status] = status_counts.get(report.status, 0) + 1
        for item in report.recommendations: recommendation_counts[item] = recommendation_counts.get(item, 0) + 1
        for item in report.next_actions: next_action_counts[item] = next_action_counts.get(item, 0) + 1
        for item in report.risk_flags: risk_counts[item] = risk_counts.get(item, 0) + 1
    recommendations = sorted(recommendation_counts, key=lambda item: (-recommendation_counts[item], item))[:max(0, int(limit_recommendations))]
    actions = sorted(next_action_counts, key=lambda item: (-next_action_counts[item], item))
    risks = [{"flag": item, "count": risk_counts[item]} for item in sorted(risk_counts, key=lambda item: (-risk_counts[item], item))]
    status = "empty" if not reports else "completed"
    seed = f"{workspace_id}:{','.join(report_ids)}:{status}"
    summary = "No reports are available for this workspace." if not reports else f"Aggregated {len(reports)} persisted commercial reports without adding unsupported market or profitability claims."
    return PortfolioReport(f"portfolio_{uuid.uuid5(uuid.NAMESPACE_URL, seed).hex[:16]}", workspace_id, title or "Commercial portfolio report", summary, report_ids, service_counts, status_counts, recommendations, risks, actions, {}, metadata={"status": status, "aggregation": "persisted_report_facts_only"})
