"""Tests for MarketOS Streamlit dashboard path confinement and data loading.

Validates that state database and report paths are strictly confined within the
intended root directory, preventing path injection (py/path-injection / CWE-22).
Covers in-root reads, traversal, absolute paths, sibling-prefix bypasses,
separator variants, symlink handling, opened-object checks, and non-echoing errors.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import pytest

from backend.monitoring.streamlit_dashboard import (
    _is_safe_regular_file,
    confine_state_path,
    load_causal_edges,
    load_drift_report,
    load_event_log,
    load_system_meta,
)


@pytest.fixture
def mock_dashboard_env(tmp_path: Path):
    """Create a temporary dashboard workspace with dummy state and drift files."""
    root = tmp_path / "app_root"
    root.mkdir(parents=True)
    state_dir = root / "state"
    state_dir.mkdir(parents=True)

    db_path = state_dir / "state.db"
    con = duckdb.connect(str(db_path))
    con.execute(
        """
        CREATE TABLE event_log (
            id INTEGER,
            roas DOUBLE,
            prediction DOUBLE,
            error DOUBLE,
            pred_width DOUBLE,
            interval_conf DOUBLE,
            cost DOUBLE,
            revenue DOUBLE,
            env_regime VARCHAR,
            env_trend VARCHAR
        );
        INSERT INTO event_log VALUES (1, 2.5, 2.4, 0.1, 0.3, 0.95, 10.0, 25.0, 'growth', 'upward');
        INSERT INTO event_log VALUES (2, 3.0, 2.8, 0.2, 0.3, 0.95, 15.0, 45.0, 'growth', 'upward');

        CREATE TABLE system_meta (
            capital DOUBLE,
            regime VARCHAR,
            detected_regime VARCHAR,
            energy_fatigue DOUBLE,
            energy_load DOUBLE,
            total_cycles INTEGER,
            env_trend VARCHAR,
            env_regime VARCHAR,
            saved_at VARCHAR
        );
        INSERT INTO system_meta VALUES (50000.0, 'growth', 'growth', 0.1, 0.2, 120, 'upward', 'growth', '2026-10-11T00:00:00');

        CREATE TABLE graph_edges (
            parent VARCHAR,
            child VARCHAR,
            weight DOUBLE
        );
        INSERT INTO graph_edges VALUES ('cpa', 'roas', 0.85);
        INSERT INTO graph_edges VALUES ('ad_spend', 'revenue', 0.92);
        """
    )
    con.close()

    drift_file = root / "drift_report.json"
    drift_file.write_text('{"any_drift": false, "total_events": 100, "share_drifted": 0.0}', encoding="utf-8")

    return {
        "root": root,
        "state_dir": state_dir,
        "db_path": db_path,
        "drift_file": drift_file,
    }


# ── In-Root Path Validation Tests ─────────────────────────────────────────────

def test_valid_in_root_relative_path(mock_dashboard_env: dict[str, Any]):
    root = mock_dashboard_env["root"]
    confined = confine_state_path("state/state.db", root=root)
    assert confined == (root / "state" / "state.db").resolve()
    assert confined.is_relative_to(root.resolve())


def test_valid_in_root_absolute_path(mock_dashboard_env: dict[str, Any]):
    root = mock_dashboard_env["root"]
    abs_path = root / "state" / "state.db"
    confined = confine_state_path(abs_path, root=root)
    assert confined == abs_path.resolve()
    assert confined.is_relative_to(root.resolve())


def test_valid_in_root_subfolder_path(mock_dashboard_env: dict[str, Any]):
    root = mock_dashboard_env["root"]
    nested = root / "data" / "archive"
    nested.mkdir(parents=True)
    custom_db = nested / "run1.db"
    custom_db.touch()

    confined = confine_state_path("data/archive/run1.db", root=root)
    assert confined == custom_db.resolve()


# ── Directory Traversal & Escape Prevention Tests ─────────────────────────────

@pytest.mark.parametrize(
    "traversal_input",
    [
        "../outside.db",
        "state/../../outside.db",
        "state/../..",
        "..\\outside.db",
        "state\\..\\..\\outside.db",
        "a/b/../../../../etc/passwd",
        "/etc/passwd",
        "C:\\Windows\\System32\\cmd.exe",
    ],
)
def test_directory_traversal_and_absolute_outside_paths_are_blocked(
    mock_dashboard_env: dict[str, Any], traversal_input: str
):
    root = mock_dashboard_env["root"]
    with pytest.raises(ValueError) as excinfo:
        confine_state_path(traversal_input, root=root)
    assert str(excinfo.value) in {"state_path_outside_root", "state_path_traversal_blocked"}
    # Assert no sensitive input is echoed
    assert traversal_input not in str(excinfo.value)


def test_sibling_prefix_directory_bypass_is_blocked(tmp_path: Path):
    """Ensure a directory sharing the root prefix (e.g. root_sibling) is rejected."""
    root = tmp_path / "app_root"
    root.mkdir()
    sibling_root = tmp_path / "app_root_sibling"
    sibling_root.mkdir()
    evil_file = sibling_root / "state.db"
    evil_file.touch()

    # If checking with str.startswith, evil_file starts with str(root) on some platforms
    with pytest.raises(ValueError, match="state_path_outside_root"):
        confine_state_path(evil_file, root=root)


def test_root_itself_and_empty_relative_rejected(mock_dashboard_env: dict[str, Any]):
    root = mock_dashboard_env["root"]
    with pytest.raises(ValueError):
        confine_state_path(".", root=root)
    with pytest.raises(ValueError):
        confine_state_path("", root=root)
    with pytest.raises(ValueError):
        confine_state_path("   ", root=root)


def test_null_bytes_and_invalid_types_rejected(mock_dashboard_env: dict[str, Any]):
    root = mock_dashboard_env["root"]
    with pytest.raises(ValueError, match="state_path_invalid"):
        confine_state_path("state/state.db\x00.evil", root=root)

    with pytest.raises(ValueError, match="state_path_invalid"):
        confine_state_path(None, root=root)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="state_path_invalid"):
        confine_state_path(12345, root=root)  # type: ignore[arg-type]


# ── Platform Separator Variants Tests ─────────────────────────────────────────

def test_platform_separator_variants(mock_dashboard_env: dict[str, Any]):
    root = mock_dashboard_env["root"]
    expected = (root / "state" / "state.db").resolve()

    # Forward slash
    assert confine_state_path("state/state.db", root=root) == expected
    # Windows backslash
    assert confine_state_path("state\\state.db", root=root) == expected
    # Mixed and redundant slashes
    assert confine_state_path("state//state.db", root=root) == expected
    assert confine_state_path("state/\\state.db", root=root) == expected


# ── Symlink & Reparse Boundary Tests ──────────────────────────────────────────

def test_symlink_inside_root_pointing_outside_is_blocked(tmp_path: Path):
    root = tmp_path / "app_root"
    root.mkdir()
    outside_file = tmp_path / "secret.db"
    outside_file.touch()

    symlink_path = root / "symlink_to_outside.db"
    try:
        os.symlink(outside_file, symlink_path)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation not permitted in this environment")

    with pytest.raises(ValueError, match="state_path_outside_root"):
        confine_state_path("symlink_to_outside.db", root=root)


def test_symlink_inside_root_pointing_inside_is_allowed(tmp_path: Path):
    root = tmp_path / "app_root"
    root.mkdir()
    target_file = root / "real_state.db"
    target_file.touch()

    symlink_path = root / "state.db"
    try:
        os.symlink(target_file, symlink_path)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation not permitted in this environment")

    confined = confine_state_path("state.db", root=root)
    assert confined == target_file.resolve()
    assert confined.is_relative_to(root.resolve())


# ── Opened-Object & File Descriptor Validation Tests ──────────────────────────

def test_is_safe_regular_file_checks(mock_dashboard_env: dict[str, Any]):
    root = mock_dashboard_env["root"]
    db_file = mock_dashboard_env["db_path"]

    # Regular file exists and is openable
    assert _is_safe_regular_file(db_file) is True

    # Directory is not a regular file
    assert _is_safe_regular_file(mock_dashboard_env["state_dir"]) is False

    # Non-existent file returns False
    assert _is_safe_regular_file(root / "nonexistent.db") is False


# ── Non-Echoing Canary Error Tests ────────────────────────────────────────────

def test_canary_tokens_never_echoed_in_exceptions(mock_dashboard_env: dict[str, Any]):
    root = mock_dashboard_env["root"]
    canary = "CANARY_TOKEN_987654321_SECRET"

    with pytest.raises(ValueError) as excinfo:
        confine_state_path(f"../../{canary}.db", root=root)
    assert canary not in str(excinfo.value)

    with pytest.raises(ValueError) as excinfo:
        confine_state_path(f"/var/secrets/{canary}", root=root)
    assert canary not in str(excinfo.value)


# ── Data Loading Integration Tests ───────────────────────────────────────────

def test_load_event_log_valid_and_confined(mock_dashboard_env: dict[str, Any]):
    root = mock_dashboard_env["root"]
    df = load_event_log("state/state.db", limit=100, root=root)
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2
    assert "roas" in df.columns
    assert "id" in df.columns


def test_load_event_log_outside_path_fails_closed(mock_dashboard_env: dict[str, Any]):
    root = mock_dashboard_env["root"]
    # Attempting to load an outside path returns an empty dataframe safely
    df = load_event_log("../../etc/passwd", root=root)
    assert isinstance(df, pd.DataFrame)
    assert df.empty


def test_load_system_meta_valid_and_confined(mock_dashboard_env: dict[str, Any]):
    root = mock_dashboard_env["root"]
    meta = load_system_meta("state/state.db", root=root)
    assert isinstance(meta, dict)
    assert meta.get("capital") == 50000.0
    assert meta.get("regime") == "growth"


def test_load_system_meta_outside_path_fails_closed(mock_dashboard_env: dict[str, Any]):
    root = mock_dashboard_env["root"]
    meta = load_system_meta("../outside.db", root=root)
    assert meta == {}


def test_load_causal_edges_valid_and_confined(mock_dashboard_env: dict[str, Any]):
    root = mock_dashboard_env["root"]
    edges_df = load_causal_edges("state/state.db", root=root)
    assert isinstance(edges_df, pd.DataFrame)
    assert len(edges_df) == 2
    assert "weight" in edges_df.columns


def test_load_causal_edges_outside_path_fails_closed(mock_dashboard_env: dict[str, Any]):
    root = mock_dashboard_env["root"]
    edges_df = load_causal_edges("../outside.db", root=root)
    assert isinstance(edges_df, pd.DataFrame)
    assert edges_df.empty


def test_load_drift_report_valid_and_missing(mock_dashboard_env: dict[str, Any]):
    root = mock_dashboard_env["root"]
    # Existing drift report
    report = load_drift_report(root=root)
    assert isinstance(report, dict)
    assert report.get("any_drift") is False

    # Missing drift report in an empty root
    empty_root = root / "empty"
    empty_root.mkdir()
    empty_report = load_drift_report(root=empty_root)
    assert empty_report == {}
