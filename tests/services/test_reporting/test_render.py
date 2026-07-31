"""Tests for services.reporting.render."""
import json

import backend.core.persistence as pers
import pytest
from backend.workspaces.artifact_store import ArtifactStore
from services.reporting.render import json_safe, render_markdown_report, save_report_artifacts


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(pers, "STATE_DIR", str(tmp_path))


def test_dry_run_disclaimer_present_when_dry_run_true():
    md = render_markdown_report("Test Report", [{"heading": "Section", "body": "hello"}], dry_run=True)
    assert "DRY RUN" in md
    assert "# Test Report" in md
    assert "## Section" in md
    assert "hello" in md


def test_dry_run_disclaimer_absent_when_dry_run_false():
    md = render_markdown_report("Test Report", [], dry_run=False)
    assert "DRY RUN" not in md


def test_renders_nested_dict_and_list_bodies():
    md = render_markdown_report(
        "Test", [{"heading": "Data", "body": {"a": 1, "items": [1, 2]}}], dry_run=False,
    )
    assert "**a**: 1" in md
    assert "[0]" in md and "[1]" in md


def test_save_report_artifacts_writes_both_files():
    store = ArtifactStore()
    result = save_report_artifacts(store, "ws-1", "exp-1", "# Report\n", {"score": 1})

    assert result == {"report_md": True, "result_json": True}
    assert store.load_text("ws-1", "exp-1", "report.md") == "# Report\n"
    assert store.load("ws-1", "exp-1", "result.json") == {"score": 1}


def test_save_report_artifacts_reflects_failure_without_raising(monkeypatch):
    store = ArtifactStore()
    monkeypatch.setattr(store, "save_text", lambda *a, **k: False)
    monkeypatch.setattr(store, "save", lambda *a, **k: False)

    result = save_report_artifacts(store, "ws-1", "exp-1", "# Report\n", {})

    assert result == {"report_md": False, "result_json": False}


class TestJsonSafe:
    def test_infinity_becomes_none(self):
        assert json_safe(float("inf")) is None
        assert json_safe(float("-inf")) is None

    def test_nan_becomes_none(self):
        assert json_safe(float("nan")) is None

    def test_finite_float_unchanged(self):
        assert json_safe(3.14) == 3.14
        assert json_safe(0.0) == 0.0

    def test_recurses_through_nested_dict_and_list(self):
        payload = {
            "a": float("inf"),
            "b": [1.0, float("nan"), {"c": float("-inf")}],
            "d": "unchanged",
            "e": 5,
        }
        result = json_safe(payload)
        assert result["a"] is None
        assert result["b"][0] == 1.0
        assert result["b"][1] is None
        assert result["b"][2]["c"] is None
        assert result["d"] == "unchanged"
        assert result["e"] == 5

    def test_output_is_actually_json_serializable(self):
        payload = {"days_since_last_posted": float("inf"), "roas": float("nan")}
        json.dumps(json_safe(payload), allow_nan=False)  # must not raise
