"""Readiness evaluation logic for consulting operations."""
from __future__ import annotations

import json
from pathlib import Path

from .schemas import (
    ConsultingEngagement,
    ConsultingReadinessReport,
    ConsultingStatus,
)


def evaluate_consulting_readiness(engagement: ConsultingEngagement) -> ConsultingReadinessReport:
    """Evaluate whether an engagement is ready for review or client service."""
    blockers: list[str] = []
    warnings: list[str] = []
    next_actions: list[str] = []

    if not engagement.intake_complete:
        blockers.append("intake_incomplete")
        next_actions.append("complete_intake_questionnaire")

    if not engagement.scope_complete:
        blockers.append("scope_incomplete")
        next_actions.append("define_project_scope")

    if engagement.missing_data_checklist:
        blockers.append("missing_required_data")
        next_actions.append(f"collect_missing_data: {', '.join(engagement.missing_data_checklist)}")

    if not engagement.evidence_provided:
        warnings.append("no_evidence_provided")

    unmet_dependencies = [
        m.name for m in engagement.planned_milestones
        if not m.completed and any(d for d in m.dependencies)
    ]
    if unmet_dependencies:
        blockers.append("unmet_milestone_dependencies")

    is_client_safe = engagement.client_safe_export_status == "approved"

    if engagement.human_review_status == "rejected":
        blockers.append("human_review_rejected")
        next_actions.append("address_review_feedback")
    elif engagement.human_review_status == "pending" and not blockers:
        next_actions.append("request_human_review")

    if blockers:
        if engagement.missing_data_checklist or not engagement.intake_complete or not engagement.scope_complete:
            status = ConsultingStatus.INCOMPLETE
        else:
            status = ConsultingStatus.BLOCKED
    elif engagement.human_review_status != "approved":
        status = ConsultingStatus.READY_FOR_REVIEW
    elif not is_client_safe:
        blockers.append("client_safe_export_pending")
        next_actions.append("approve_client_export")
        status = ConsultingStatus.BLOCKED
    elif not engagement.handoff_checklist_complete:
        blockers.append("handoff_checklist_incomplete")
        next_actions.append("complete_handoff_checklist")
        status = ConsultingStatus.BLOCKED
    else:
        status = ConsultingStatus.READY_FOR_CLIENT_SERVICE
        next_actions.append("schedule_client_handoff")

    if engagement.upgrade_readiness == "ready":
        warnings.append("upsell_opportunity_available")

    return ConsultingReadinessReport(
        engagement_id=engagement.engagement_id,
        status=status,
        blockers=tuple(blockers),
        next_actions=tuple(next_actions),
        is_client_safe=is_client_safe,
        warnings=tuple(warnings),
    )


def generate_readiness_report(engagement: ConsultingEngagement, output_format: str = "json") -> str:
    """Generate a formatted readiness report."""
    report = evaluate_consulting_readiness(engagement)

    if output_format == "json":
        return json.dumps(report.to_dict(), indent=2)

    # Markdown format
    lines = [
        f"# Consulting Readiness Report: {engagement.engagement_id}",
        f"**Status:** {report.status.value}",
        f"**Client Safe:** {'Yes' if report.is_client_safe else 'No'}",
        "",
    ]

    if report.blockers:
        lines.append("## Blockers")
        for b in report.blockers:
            lines.append(f"- {b}")
        lines.append("")

    if report.warnings:
        lines.append("## Warnings")
        for w in report.warnings:
            lines.append(f"- {w}")
        lines.append("")

    if report.next_actions:
        lines.append("## Next Actions")
        for a in report.next_actions:
            lines.append(f"- {a}")

    return "\n".join(lines)
