"""Stable JSON and Markdown renderers for shadow-evaluation reports."""
from __future__ import annotations

import json

from .models import EvaluationReport


def report_to_json(report: EvaluationReport) -> str:
    return json.dumps(report.to_dict(), sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def report_to_markdown(report: EvaluationReport) -> str:
    rows = [
        "# Shadow Feature Evaluation Report",
        "",
        "This is a deterministic, read-only certification report. It does not change feature flags or production behavior.",
        "",
        f"- Report: `{report.report_id}`",
        f"- Fixtures: {', '.join(report.fixtures_evaluated)}",
        f"- Generated from latest synthetic event timestamp: `{report.generated_at}`",
        "",
        "| Fixture | Feature | Classification | Sample | Blockers |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for item in report.features:
        blockers = ", ".join(item.blockers) if item.blockers else "none"
        rows.append(f"| {item.fixture_name} | {item.feature_id} | **{item.classification}** | {item.sample_size} | {blockers} |")
    rows.extend(["", "## Evidence detail", ""])
    for item in report.features:
        metric = item.primary_metrics[0]
        rows.extend([
            f"### {item.fixture_name}: {item.feature_id}",
            "",
            f"- Primary metric: `{metric.name}` baseline `{metric.baseline_value}` -> candidate `{metric.candidate_value}` (delta `{metric.delta}`).",
            f"- Required event evidence: {', '.join(item.requirement.required_event_types)}.",
            f"- Evidence event IDs: {', '.join(item.evidence_event_ids) or 'none'}.",
            f"- Rationale: {', '.join(item.rationale)}.",
            f"- Recommendation: {item.recommendation}",
            "",
        ])
    rows.extend(["", "## Next actions", ""])
    rows.extend(f"- {action}" for action in report.recommended_next_actions)
    rows.extend(["", "## Safety", "", "- No provider calls, feature-flag changes, live authority, or external mutation occur."])
    return "\n".join(rows) + "\n"
