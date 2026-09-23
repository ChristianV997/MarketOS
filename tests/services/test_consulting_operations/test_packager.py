"""Tests for the consulting delivery packager."""
from __future__ import annotations

import json
import pytest

from services.consulting_operations.schemas import ConsultingEngagement
from services.consulting_operations.packager import package_deliverable


def test_package_deliverable_success():
    engagement = ConsultingEngagement(
        engagement_id="eng-1",
        package_id="pkg-1",
        workspace_id="ws-1",
        owner="owner-1",
    )
    reports = {
        "commercial": {"summary": "test"},
        "invalid_type": {"should_be": "ignored"},
    }
    deliverable = package_deliverable(engagement, reports)
    assert deliverable.engagement_id == "eng-1"
    assert "commercial" in deliverable.payload
    assert "invalid_type" not in deliverable.payload


def test_package_deliverable_missing_reports():
    engagement = ConsultingEngagement(
        engagement_id="eng-1",
        package_id="pkg-1",
        workspace_id="ws-1",
        owner="owner-1",
    )
    reports = {
        "commercial": {"summary": "test"},
    }
    with pytest.raises(ValueError, match="Missing required reports"):
        package_deliverable(engagement, reports, required_reports=("economics",))


def test_package_deliverable_malformed_dependency():
    engagement = ConsultingEngagement(
        engagement_id="eng-1",
        package_id="pkg-1",
        workspace_id="ws-1",
        owner="owner-1",
    )
    reports = {
        "commercial": "not a dict",
    }
    with pytest.raises(ValueError, match="Malformed dependency"):
        package_deliverable(engagement, reports)


def test_package_deliverable_unapproved_live_evidence():
    engagement = ConsultingEngagement(
        engagement_id="eng-1",
        package_id="pkg-1",
        workspace_id="ws-1",
        owner="owner-1",
    )
    reports = {
        "commercial": {
            "live_execution": True,
            "live_approved": False,
        }
    }
    with pytest.raises(ValueError, match="Unapproved live evidence"):
        package_deliverable(engagement, reports)


def test_package_deliverable_workspace_leakage():
    engagement = ConsultingEngagement(
        engagement_id="eng-1",
        package_id="pkg-1",
        workspace_id="ws-1",
        owner="owner-1",
    )
    reports = {
        "commercial": {
            "internal_prompt": "secret prompt",
        }
    }
    with pytest.raises(ValueError, match="Workspace isolation violation"):
        package_deliverable(engagement, reports)

def test_package_deliverable_size_limit():
    engagement = ConsultingEngagement(
        engagement_id="eng-1",
        package_id="pkg-1",
        workspace_id="ws-1",
        owner="owner-1",
    )
    reports = {
        "commercial": {
            "huge_data": "x" * (6 * 1024 * 1024),
        }
    }
    with pytest.raises(ValueError, match="exceeds max"):
        package_deliverable(engagement, reports)
