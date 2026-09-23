"""End-to-end tests through the documented operator entry point
(scripts/market_research_report.py), not just through
build_market_research_report directly. Exercises both an in-process
main() call and a real subprocess CLI invocation, so a regression in
argument parsing or manifest loading is caught even though the report
builder's own unit tests would still pass.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "market_research_report.py"
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "market_research"

sys.path.insert(0, str(REPO_ROOT))
from scripts.market_research_report import MarketResearchOperatorError, load_manifest, main  # noqa: E402


def test_load_manifest_rejects_missing_file(tmp_path):
    with pytest.raises(MarketResearchOperatorError):
        load_manifest(str(tmp_path / "does_not_exist.json"))


def test_load_manifest_rejects_invalid_json(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(MarketResearchOperatorError):
        load_manifest(str(bad))


def test_main_emits_json_report_with_conflict_findings_and_provenance(capsys):
    exit_code = main(["--manifest", str(FIXTURES / "manifest_inline.json")])
    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["candidate_id"] == "cand-1"
    assert output["workspace_id"] == "workspace-operator-1"
    assert "conflict_findings" in output
    assert "source_provenance" in output
    assert "blockers" in output
    assert "next_research_actions" in output
    assert output["blockers"], "missing consumer/public-market evidence must produce blockers end to end"


def test_main_emits_markdown_report(capsys):
    exit_code = main(["--manifest", str(FIXTURES / "manifest_inline.json"), "--markdown"])
    assert exit_code == 0
    markdown = capsys.readouterr().out
    assert markdown.startswith("# MarketOS Market Research Report")
    assert "Deterministic Conflict Findings" in markdown
    assert "Observation & Source Provenance" in markdown
    assert "Next Research Actions" in markdown


def test_main_resolves_a_report_path_relative_to_the_manifest(capsys):
    exit_code = main(["--manifest", str(FIXTURES / "manifest_with_path.json")])
    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["competitor_and_substitute_evidence"]["status"] == "supplied"


def test_main_writes_to_an_output_file_when_requested(tmp_path):
    out_file = tmp_path / "report.json"
    exit_code = main(["--manifest", str(FIXTURES / "manifest_inline.json"), "--output", str(out_file)])
    assert exit_code == 0
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["candidate_id"] == "cand-1"


def test_main_rejects_manifest_missing_candidate_id(tmp_path, capsys):
    manifest = tmp_path / "no_candidate.json"
    manifest.write_text(json.dumps({"workspace_id": "ws-1"}), encoding="utf-8")
    exit_code = main(["--manifest", str(manifest)])
    assert exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "rejected"


def test_main_rejects_a_report_path_that_escapes_the_manifest_directory(tmp_path, capsys):
    manifest = tmp_path / "escape.json"
    manifest.write_text(json.dumps({"candidate_id": "c1", "marketplace_report_path": "../../etc/passwd"}), encoding="utf-8")
    exit_code = main(["--manifest", str(manifest)])
    assert exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "rejected"


def test_real_cli_subprocess_produces_the_same_json_as_the_in_process_call(capsys):
    """Proves the actual `python scripts/market_research_report.py` entry
    point works untouched by test-harness import shortcuts."""
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--manifest", str(FIXTURES / "manifest_inline.json")],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    subprocess_output = json.loads(completed.stdout)

    main(["--manifest", str(FIXTURES / "manifest_inline.json")])
    in_process_output = json.loads(capsys.readouterr().out)

    subprocess_output.pop("generated_at")
    in_process_output.pop("generated_at")
    assert subprocess_output == in_process_output
