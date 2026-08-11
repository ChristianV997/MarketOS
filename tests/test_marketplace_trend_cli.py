"""CLI contract tests for the offline marketplace trend runner."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.run_marketplace_trend_intelligence import main

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "marketplace_trends"


def test_default_json_mode_is_deterministic(capsys):
    assert main(["--json"]) == 0
    first = capsys.readouterr().out
    assert main(["--json"]) == 0
    second = capsys.readouterr().out
    assert json.loads(first) == json.loads(second)


def test_markdown_mode_has_safety_language(capsys):
    assert main(["--markdown"]) == 0
    output = capsys.readouterr().out
    assert "Marketplace Trend Intelligence" in output
    assert "not supplier proof" in output
    assert "no network calls" in output.lower()


def test_manual_import_mode_reports_manual_evidence(capsys):
    assert main(["--manual-import", str(FIXTURES / "ebay_terapeak_import.csv"), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["evidence_mode"] == "manual_import"
    assert report["candidate_count"] == 2


def test_marketplace_filter_keeps_only_requested_source(capsys):
    assert main(["--manual-import", str(FIXTURES / "manual_import_mixed_marketplaces.csv"), "--marketplace", "amazon", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["marketplaces_observed"] == ["amazon"]
    assert report["candidate_count"] == 1


def test_candidate_seed_with_metadata_is_safe_empty_evidence(capsys):
    assert main(["--candidate-seed", str(FIXTURES / "candidates.json"), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["candidate_count"] == 10
    assert report["candidates"][0]["score"]["recommendation"] == "reject_low_signal"


def test_output_writes_only_allowed_files(tmp_path, capsys):
    assert main(["--output", str(tmp_path), "--json"]) == 0
    capsys.readouterr()
    assert {path.name for path in tmp_path.iterdir()} == {
        "marketplace_trend_report.json",
        "marketplace_trend_report.md",
        "marketplace_source_summary.json",
    }
    report = json.loads((tmp_path / "marketplace_trend_report.json").read_text(encoding="utf8"))
    assert report["read_only"] is True
    assert report["network_calls"] is False
    assert report["mutated"] is False


def test_output_report_is_json_stable(tmp_path, capsys):
    main(["--output", str(tmp_path), "--json"])
    capsys.readouterr()
    first = (tmp_path / "marketplace_trend_report.json").read_text(encoding="utf8")
    main(["--output", str(tmp_path), "--json"])
    capsys.readouterr()
    assert first == (tmp_path / "marketplace_trend_report.json").read_text(encoding="utf8")


def test_max_candidate_bound_is_enforced(capsys):
    main(["--manual-import", str(FIXTURES / "manual_import_mixed_marketplaces.csv"), "--max-candidates", "1", "--json"])
    report = json.loads(capsys.readouterr().out)
    assert report["candidate_count"] == 1


def test_max_source_bound_is_enforced(capsys):
    main(["--candidate-seed", str(FIXTURES / "amazon_best_sellers_snapshot.json"), "--max-sources-per-candidate", "1", "--json"])
    report = json.loads(capsys.readouterr().out)
    assert all(len(item["evidence"]) <= 1 for item in report["candidates"])


def test_network_mode_is_explicitly_rejected(capsys):
    with pytest.raises(SystemExit):
        main(["--allow-network", "--json"])
    assert "network mode is not implemented" in capsys.readouterr().err


def test_json_and_markdown_cannot_be_combined():
    with pytest.raises(SystemExit):
        main(["--json", "--markdown"])


def test_invalid_bounds_are_rejected():
    with pytest.raises(SystemExit):
        main(["--max-candidates", "0", "--json"])


def test_invalid_input_path_is_reported(capsys, tmp_path):
    with pytest.raises(SystemExit):
        main(["--candidate-seed", str(tmp_path / "missing.json"), "--json"])
    assert "does not exist" in capsys.readouterr().err


def test_manual_report_markdown_lists_candidate(capsys):
    main(["--manual-import", str(FIXTURES / "ebay_terapeak_import.csv"), "--markdown"])
    output = capsys.readouterr().out
    assert "mini-thermal-printer" in output
    assert "Next action:" in output


def test_source_summary_is_sanitized(tmp_path, capsys):
    main(["--output", str(tmp_path), "--manual-import", str(FIXTURES / "ebay_terapeak_import.csv"), "--json"])
    capsys.readouterr()
    summary = json.loads((tmp_path / "marketplace_source_summary.json").read_text(encoding="utf8"))
    assert set(summary) == {"marketplaces", "source_count", "candidate_count", "best_seller_evidence_count", "read_only", "network_calls", "mutated"}
    assert "api_key" not in json.dumps(summary).lower()
