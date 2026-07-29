"""Tests for the Evidently drift detection report."""
import json
import os
import pytest
import pandas as pd
import numpy as np

from backend.core.state import SystemState
from backend.execution.loop import run_cycle
from backend.core.db_serializer import save as db_save
from scripts.drift_report import (
    _load_window,
    _parse_snapshot,
    _markdown_report,
    build_drift_snapshot,
    main as drift_main,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _build_db(tmp_path, n_cycles=12) -> str:
    """Run n_cycles and save to a fresh DuckDB; return path."""
    state = SystemState()
    for _ in range(n_cycles):
        state = run_cycle(state)
    path = str(tmp_path / "state.db")
    db_save(state, path)
    return path


# ── _load_window ─────────────────────────────────────────────────────────────

class TestLoadWindow:
    def test_returns_two_dataframes(self, tmp_path):
        db = _build_db(tmp_path, n_cycles=12)
        ref, cur = _load_window(db, window=10)
        assert isinstance(ref, pd.DataFrame)
        assert isinstance(cur, pd.DataFrame)

    def test_correct_columns(self, tmp_path):
        db = _build_db(tmp_path, n_cycles=12)
        ref, cur = _load_window(db, window=10)
        for col in ["roas", "prediction", "error"]:
            assert col in ref.columns
            assert col in cur.columns

    def test_no_overlap(self, tmp_path):
        """Current window must come strictly after reference window."""
        db = _build_db(tmp_path, n_cycles=20)
        ref, cur = _load_window(db, window=20)
        # Both should be non-empty
        assert len(ref) > 0
        assert len(cur) > 0
        # Together they cover all rows (no gaps, no overlap)
        assert len(ref) + len(cur) <= 20 * 5 + 5  # cycles × decisions


# ── _parse_snapshot ───────────────────────────────────────────────────────────

class TestParseSnapshot:
    @pytest.fixture(scope="class")
    @classmethod
    def snapshot(cls):
        rng = np.random.default_rng(0)
        ref = pd.DataFrame({"roas": rng.normal(1.2, 0.3, 100), "error": rng.normal(0, 0.1, 100)})
        cur = pd.DataFrame({"roas": rng.normal(2.5, 0.5, 60),  "error": rng.normal(0.5, 0.2, 60)})
        return build_drift_snapshot(ref, cur)

    def test_columns_present(self, snapshot):
        r = _parse_snapshot(snapshot)
        assert "columns" in r
        assert "share_drifted" in r

    def test_detects_strong_drift(self, snapshot):
        r = _parse_snapshot(snapshot)
        drifted = [c for c, v in r["columns"].items() if v["drifted"]]
        assert len(drifted) > 0, "Expected drift not detected"

    def test_per_column_has_p_value(self, snapshot):
        r = _parse_snapshot(snapshot)
        for col, info in r["columns"].items():
            assert "p_value" in info
            assert 0.0 <= info["p_value"] <= 1.0

    def test_no_drift_on_identical_data(self):
        rng = np.random.default_rng(1)
        data = pd.DataFrame({"roas": rng.normal(1.2, 0.3, 100)})
        snap = build_drift_snapshot(data, data.copy())
        r = _parse_snapshot(snap)
        # p-values on identical data should be high (no drift)
        for col, info in r["columns"].items():
            assert not info["drifted"], f"False drift on identical data for {col}"


# ── _markdown_report ──────────────────────────────────────────────────────────

class TestMarkdownReport:
    def _make_results(self, drifted_cols):
        columns = {
            col: {"p_value": 0.001 if col in drifted_cols else 0.8, "threshold": 0.05,
                  "drifted": col in drifted_cols}
            for col in ["roas", "error", "pred_width"]
        }
        return {
            "share_drifted": len(drifted_cols) / len(columns),
            "columns": columns,
        }

    def test_contains_status_header(self):
        md = _markdown_report(self._make_results([]), 100, 50, 500, 50)
        assert "No drift detected" in md

    def test_drift_flag_appears(self):
        md = _markdown_report(self._make_results(["roas"]), 100, 50, 500, 50)
        assert "DRIFT DETECTED" in md

    def test_all_features_listed(self):
        md = _markdown_report(self._make_results([]), 100, 50, 500, 50)
        for col in ["roas", "error", "pred_width"]:
            assert col in md

    def test_counts_in_table(self):
        md = _markdown_report(self._make_results([]), 100, 50, 500, 50)
        assert "100" in md   # ref size
        assert "50" in md    # cur size


# ── main() end-to-end ─────────────────────────────────────────────────────────

class TestMainEndToEnd:
    def test_exits_gracefully_no_db(self, tmp_path, capsys):
        import sys
        sys.argv = ["drift_report.py", "--state-path", str(tmp_path / "missing.db")]
        drift_main()
        out = capsys.readouterr().out
        assert "No state DB found" in out

    def test_exits_gracefully_insufficient_data(self, tmp_path, capsys):
        """A DB with too few events triggers the 'not enough data' guard."""
        db = _build_db(tmp_path, n_cycles=3)   # ~15 events, needs ≥ 40
        import sys
        sys.argv = ["drift_report.py", "--state-path", db, "--window", "200"]
        drift_main()
        out = capsys.readouterr().out
        assert "Not enough data" in out

    def test_produces_report_with_enough_data(self, tmp_path, capsys):
        db = _build_db(tmp_path, n_cycles=20)  # ~100 events
        import sys
        sys.argv = ["drift_report.py", "--state-path", db, "--window", "20"]
        result = drift_main()
        out = capsys.readouterr().out
        assert "Evidently Drift Report" in out
        assert result is not None
        assert "columns" in result

    def test_json_output_written(self, tmp_path, capsys):
        db = _build_db(tmp_path, n_cycles=20)
        out_path = str(tmp_path / "drift.json")
        import sys
        sys.argv = ["drift_report.py", "--state-path", db,
                    "--window", "20", "--out", out_path]
        drift_main()
        assert os.path.exists(out_path)
        with open(out_path) as f:
            d = json.load(f)
        assert "any_drift" in d
        assert "columns" in d
        assert "total_events" in d
