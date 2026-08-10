from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _run(*args: str, timeout: int = 60):
    return subprocess.run(
        [sys.executable, "scripts/run_phase1_live_validation.py", *args],
        cwd=ROOT, text=True, capture_output=True, check=True, timeout=timeout,
    )


class TestDryRunEndToEnd:
    def test_full_chain_runs_and_degrades_honestly_without_allow_network(self, tmp_path):
        out_dir = tmp_path / "run1"
        result = _run(
            "--supplier-url", "https://www.cjdropshipping.com/product/x.html",
            "--competitor-urls", "https://example.com/a,https://example.com/b",
            "--out-dir", str(out_dir), "--timestamp", "test-run-1",
        )
        report = json.loads(result.stdout)
        assert report["status"] == "degraded_dry_run"
        assert report["network_status"]["allow_network"] is False
        assert all(diag["failure_mode"] == "not_attempted" for diag in report["network_status"]["diagnosis"])
        assert report["supplier_evidence"]["status"] == "unavailable"
        assert report["competition_evidence"]["status"] == "unavailable"
        assert report["read_only"] is True
        assert report["mutated"] is False

    def test_writes_json_artifact_to_out_dir(self, tmp_path):
        out_dir = tmp_path / "run2"
        _run("--out-dir", str(out_dir), "--timestamp", "test-run-2")
        artifact = out_dir / "validation_report.json"
        assert artifact.exists()
        payload = json.loads(artifact.read_text(encoding="utf-8"))
        assert payload["status"] == "degraded_dry_run"

    def test_markdown_flag_writes_second_artifact(self, tmp_path):
        out_dir = tmp_path / "run3"
        _run("--out-dir", str(out_dir), "--timestamp", "test-run-3", "--markdown")
        assert (out_dir / "validation_report.json").exists()
        markdown = (out_dir / "validation_report.md").read_text(encoding="utf-8")
        assert "Phase 1 live validation report" in markdown
        assert "Next action" in markdown

    def test_no_urls_supplied_reports_no_url_supplied_status(self, tmp_path):
        out_dir = tmp_path / "run4"
        result = _run("--out-dir", str(out_dir), "--timestamp", "test-run-4")
        report = json.loads(result.stdout)
        assert report["supplier_evidence"]["status"] == "no_url_supplied"
        assert report["competition_evidence"]["status"] == "no_urls_supplied"

    def test_events_written_and_read_path_verified(self, tmp_path):
        out_dir = tmp_path / "run5"
        result = _run("--out-dir", str(out_dir), "--timestamp", "test-run-5")
        report = json.loads(result.stdout)
        events_path = ROOT / report["api_dashboard_read_path"]["events_path"]
        assert events_path.exists()
        assert report["api_dashboard_read_path"]["events_replayed"] > 0
        assert report["api_dashboard_read_path"]["commerce_runs_readable"] is True
        assert report["api_dashboard_read_path"]["opportunity_rankings_readable"] is True
        assert report["api_dashboard_read_path"]["research_portfolios_readable"] is True
        events_path.unlink()

    def test_canonical_event_types_span_full_chain(self, tmp_path):
        out_dir = tmp_path / "run6"
        result = _run(
            "--supplier-url", "https://www.cjdropshipping.com/product/x.html",
            "--competitor-urls", "https://example.com/a",
            "--out-dir", str(out_dir), "--timestamp", "test-run-6",
        )
        report = json.loads(result.stdout)
        types = set(report["canonical_event_types"])
        assert {"commerce_mvp_run_started", "commerce_mvp_run_completed", "opportunity_scoring_started",
                "candidate_discovered", "research_portfolio_updated", "research_completed"} <= types

    def test_deterministic_given_fixed_timestamp(self, tmp_path):
        out_dir_a, out_dir_b = tmp_path / "a", tmp_path / "b"
        first = json.loads(_run("--out-dir", str(out_dir_a), "--timestamp", "fixed-ts").stdout)
        second = json.loads(_run("--out-dir", str(out_dir_b), "--timestamp", "fixed-ts").stdout)
        first.pop("api_dashboard_read_path")  # events_path differs by out_dir
        second.pop("api_dashboard_read_path")
        assert first == second

    def test_default_out_dir_lands_under_artifacts(self):
        result = _run("--timestamp", "test-default-dir")
        expected = ROOT / "artifacts" / "phase1_live_validation" / "test-default-dir"
        try:
            assert (expected / "validation_report.json").exists()
        finally:
            import shutil
            shutil.rmtree(expected, ignore_errors=True)
