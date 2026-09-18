"""Validate the active frontend/API boundary plan metadata."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
PLAN = ROOT / "docs/plans/active/plan-marketos-frontend-api-boundary-v2.md"

REQUIRED_SECTIONS = (
    "## Risk",
    "## Stop conditions",
    "## Target files",
    "## Interface contracts",
    "## Verification commands",
    "## Acceptance criteria",
    "## Recovery conditions",
)


def test_frontend_boundary_plan_contains_required_metadata():
    text = PLAN.read_text(encoding="utf-8")
    assert "frontend_api_boundary" in text
    assert "LOW" in text
    assert "frontend/package-lock.json" in text
    for section in REQUIRED_SECTIONS:
        assert section in text, f"missing plan section: {section}"
