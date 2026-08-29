"""Validate the active low-risk service pilot plan metadata."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
PLAN = ROOT / "docs/plans/active/plan-marketos-low-risk-service-pilot-v1.md"

REQUIRED_SECTIONS = (
    "## Lane",
    "## Risk",
    "## Ownership",
    "## Stop Conditions",
    "## Target Files",
    "## Interface Contracts",
    "## Verification Commands",
    "## Acceptance Criteria",
    "## Recovery Conditions",
)


def test_plan_exists_and_contains_required_metadata():
    text = PLAN.read_text(encoding="utf-8")
    assert "Status:** `active`" in text or "Status: `active`" in text
    assert "human_operator" in text
    assert '"level": "LOW"' in text
    for section in REQUIRED_SECTIONS:
        assert section in text, f"missing plan section: {section}"


def test_plan_target_files_are_bounded():
    text = PLAN.read_text(encoding="utf-8")
    assert "services/unit_economics/analyzer.py" in text
    assert "tests/services/test_unit_economics/test_low_risk_service_pilot.py" in text
    assert "orchestrators" in text  # out-of-scope guard
    assert not re.search(r"services/reporting/", text)


def test_plan_verification_commands_reference_pilot_tests():
    text = PLAN.read_text(encoding="utf-8")
    assert "tests/services/test_unit_economics/" in text
    assert "tests/test_plan_marketos_low_risk_service_pilot.py" in text
