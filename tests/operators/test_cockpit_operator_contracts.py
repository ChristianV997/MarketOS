"""Cockpit operator-critical contracts. Skip when PR #230 files are absent."""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COCKPIT = ROOT / "frontend/src/features/first-phase-cockpit"


pytestmark = pytest.mark.skipif(not COCKPIT.is_dir(), reason="first-phase cockpit owned by PR #230; not on this branch")


def _read(rel: str) -> str:
    return (COCKPIT / rel).read_text(encoding="utf-8")


def test_filters_and_windows_do_not_sort():
    assert ".sort(" not in _read("lib/filterCandidates.ts")
    assert ".sort(" not in _read("lib/windowCandidates.ts")
    assert "slice(" in _read("lib/windowCandidates.ts")


def test_keyboard_and_detail_focus_contracts():
    table = _read("components/RankedCandidatesPanel.tsx")
    nav = _read("lib/keyboardNav.ts")
    detail = _read("components/CandidateDetailPanel.tsx")
    assert "ArrowDown" in nav
    assert "ArrowUp" in nav
    assert "Home" in nav
    assert "End" in nav
    assert "adjacentCandidateIndex" in table
    assert "shouldHandoffDetailFocus" in table
    assert "Home" in table
    assert "End" in table
    assert 'id="candidate-detail-panel"' in detail
    assert "Escape" in detail
    assert "returnFocusToTable" in detail
    assert 'role="grid"' in table
    assert "aria-selected" in table
    assert 'role="listbox"' in table


def test_partial_and_stale_states_exist():
    banner = _read("components/CockpitStatusBanner.tsx")
    assert "partial" in banner
    assert "stale" in banner


def test_schema_and_secret_export_guards():
    validate = _read("lib/validateEvidencePacket.ts")
    export = _read("lib/exportClientSafeReport.ts")
    assert "schema_version_unsupported" in validate
    assert "secret_shaped" in export.lower() or "SECRET_SHAPED" in export
