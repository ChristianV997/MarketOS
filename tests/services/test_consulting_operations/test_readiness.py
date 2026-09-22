"""Tests for consulting operations readiness evaluation."""
from __future__ import annotations

import json
import pytest

from services.consulting_operations.schemas import (
    ConsultingEngagement,
    ConsultingMilestone,
    ConsultingStatus,
)
from services.consulting_operations.readiness import (
    evaluate_consulting_readiness,
    generate_readiness_report,
)


def test_incomplete_intake_fails_closed():
    engagement = ConsultingEngagement(
        engagement_id="eng-1",
        package_id="pkg-1",
        workspace_id="ws-1",
        owner="owner-1",
    )
    report = evaluate_consulting_readiness(engagement)
    assert report.status == ConsultingStatus.INCOMPLETE
    assert "intake_incomplete" in report.blockers
    assert not report.is_client_safe


def test_missing_data_fails_closed():
    engagement = ConsultingEngagement(
        engagement_id="eng-2",
        package_id="pkg-1",
        workspace_id="ws-1",
        owner="owner-1",
        intake_complete=True,
        scope_complete=True,
        missing_data_checklist=("client_logo", "brand_guidelines"),
    )
    report = evaluate_consulting_readiness(engagement)
    assert report.status == ConsultingStatus.INCOMPLETE
    assert "missing_required_data" in report.blockers


def test_ready_for_review_state():
    engagement = ConsultingEngagement(
        engagement_id="eng-3",
        package_id="pkg-1",
        workspace_id="ws-1",
        owner="owner-1",
        intake_complete=True,
        scope_complete=True,
        evidence_provided=("doc-1",),
    )
    report = evaluate_consulting_readiness(engagement)
    assert report.status == ConsultingStatus.READY_FOR_REVIEW
    assert "request_human_review" in report.next_actions


def test_ready_for_client_service_state():
    engagement = ConsultingEngagement(
        engagement_id="eng-4",
        package_id="pkg-1",
        workspace_id="ws-1",
        owner="owner-1",
        intake_complete=True,
        scope_complete=True,
        evidence_provided=("doc-1",),
        client_safe_export_status="approved",
        human_review_status="approved",
        handoff_checklist_complete=True,
    )
    report = evaluate_consulting_readiness(engagement)
    assert report.status == ConsultingStatus.READY_FOR_CLIENT_SERVICE
    assert report.is_client_safe
    assert not report.blockers


def test_unsafe_client_export_blocks_delivery():
    engagement = ConsultingEngagement(
        engagement_id="eng-5",
        package_id="pkg-1",
        workspace_id="ws-1",
        owner="owner-1",
        intake_complete=True,
        scope_complete=True,
        human_review_status="approved",
        client_safe_export_status="rejected",
    )
    report = evaluate_consulting_readiness(engagement)
    assert report.status == ConsultingStatus.BLOCKED
    assert "client_safe_export_pending" in report.blockers
    assert not report.is_client_safe


def test_json_report_generation():
    engagement = ConsultingEngagement(
        engagement_id="eng-6",
        package_id="pkg-1",
        workspace_id="ws-1",
        owner="owner-1",
    )
    report_str = generate_readiness_report(engagement, output_format="json")
    data = json.loads(report_str)
    assert data["engagement_id"] == "eng-6"
    assert data["status"] == "incomplete"


def test_markdown_report_generation():
    engagement = ConsultingEngagement(
        engagement_id="eng-7",
        package_id="pkg-1",
        workspace_id="ws-1",
        owner="owner-1",
        intake_complete=True,
        scope_complete=True,
        human_review_status="approved",
        client_safe_export_status="approved",
        handoff_checklist_complete=True,
        upgrade_readiness="ready",
    )
    report_str = generate_readiness_report(engagement, output_format="markdown")
    assert "# Consulting Readiness Report: eng-7" in report_str
    assert "**Status:** ready_for_client_service" in report_str
    assert "upsell_opportunity_available" in report_str
