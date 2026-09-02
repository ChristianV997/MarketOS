"""Contract tests for the Windows first-phase intelligence operator wrapper."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "operators" / "run_first_phase_intelligence.ps1"
FIXTURES = ROOT / "tests" / "fixtures"
MARKETPLACE_FIXTURES = FIXTURES / "marketplace_trends"


def _run_operator(*args: str, python_path: str | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(SCRIPT),
        *args,
    ]
    if python_path is not None:
        command.extend(["-PythonPath", python_path])
    return subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env or os.environ.copy(),
        timeout=300,
    )


def _summary_from_output(output: str) -> dict:
    lines = [line.strip() for line in output.splitlines() if line.strip().startswith("{")]
    assert lines, f"expected deterministic summary JSON in output:\n{output}"
    return json.loads(lines[-1])


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell operator wrapper is Windows-only")
def test_default_offline_behavior_is_fixture_first():
    result = _run_operator()
    assert result.returncode == 0, result.stderr
    summary = _summary_from_output(result.stdout)
    assert summary["evidence_mode"] == "fixture_demo"
    assert summary["overall_classification"] == "actual"
    assert summary["read_only"] is True
    assert summary["network_calls"] is False
    assert summary["mutated"] is False
    assert summary["output_directory"] is None
    assert [stage["classification"] for stage in summary["stages"]] == ["actual"] * 8


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell operator wrapper is Windows-only")
def test_explicit_output_directory_writes_stage_artifacts(tmp_path: Path):
    output_dir = tmp_path / "phase1 out"
    result = _run_operator("-OutputDirectory", str(output_dir), "-MaxCandidates", "2")
    assert result.returncode == 0, result.stderr
    summary = _summary_from_output(result.stdout)
    assert summary["output_directory"] is not None
    marketplace = output_dir / "marketplace_trend" / "marketplace_trend_report.json"
    synthesis = output_dir / "opportunity_synthesis" / "opportunity_synthesis_report.json"
    validation = output_dir / "product_validation" / "product_validation_report.json"
    governor = output_dir / "resource_governor" / "resource_execution_governor_report.json"
    trustos = output_dir / "trustos_control_plane" / "trustos_report.json"
    assert marketplace.is_file()
    assert synthesis.is_file()
    assert validation.is_file()
    assert governor.is_file()
    assert trustos.is_file()
    report = json.loads(marketplace.read_text(encoding="utf-8"))
    assert report["candidate_count"] <= 2


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell operator wrapper is Windows-only")
def test_missing_python_exits_with_unavailable_code(tmp_path: Path):
    missing = tmp_path / "missing-python.exe"
    result = _run_operator("-PythonPath", str(missing))
    assert result.returncode == 3
    assert "python interpreter not found" in result.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell operator wrapper is Windows-only")
def test_malformed_input_is_rejected_before_stages(tmp_path: Path):
    missing = tmp_path / "does-not-exist.csv"
    result = _run_operator("-MarketplaceTrendImport", str(missing))
    assert result.returncode == 2
    assert "does not exist" in result.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell operator wrapper is Windows-only")
def test_blocked_live_flags_are_rejected():
    result = _run_operator("-AllowNetwork")
    assert result.returncode == 4
    assert "blocked live/network/provider/model flag" in result.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell operator wrapper is Windows-only")
def test_bounded_candidate_count_is_enforced(tmp_path: Path):
    output_dir = tmp_path / "bounded"
    result = _run_operator("-OutputDirectory", str(output_dir), "-MaxCandidates", "1")
    assert result.returncode == 0, result.stderr
    report = json.loads((output_dir / "marketplace_trend" / "marketplace_trend_report.json").read_text(encoding="utf-8"))
    assert report["candidate_count"] == 1


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell operator wrapper is Windows-only")
def test_stage_failure_propagates_and_stops_pipeline(tmp_path: Path):
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{not-json", encoding="utf-8")
    result = _run_operator("-MarketplaceTrendSeed", str(bad_json))
    assert result.returncode != 0
    summary = _summary_from_output(result.stdout)
    stage_ids = [stage["id"] for stage in summary["stages"]]
    assert "marketplace_trend" in stage_ids
    assert "commerce_mvp" not in stage_ids
    assert summary["overall_classification"] == "failed"


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell operator wrapper is Windows-only")
def test_repeated_invocation_is_deterministic():
    first = _run_operator("-MaxCandidates", "2")
    second = _run_operator("-MaxCandidates", "2")
    assert first.returncode == 0 and second.returncode == 0
    summary_first = _summary_from_output(first.stdout)
    summary_second = _summary_from_output(second.stdout)
    assert summary_first["stages"] == summary_second["stages"]
    assert summary_first["evidence_mode"] == summary_second["evidence_mode"]


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell operator wrapper is Windows-only")
def test_safe_output_path_rejects_artifacts_directory():
    artifacts_target = ROOT / "artifacts" / "operator-phase1-test"
    result = _run_operator("-OutputDirectory", str(artifacts_target))
    assert result.returncode == 2
    assert "artifacts" in result.stderr.lower()


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell operator wrapper is Windows-only")
def test_no_default_writes_to_artifacts_or_credentials(tmp_path: Path):
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    before = list(artifacts_dir.iterdir())
    result = _run_operator()
    assert result.returncode == 0
    after = list(artifacts_dir.iterdir())
    assert before == after
    assert "sk-" not in result.stdout.lower()
    assert "api_key" not in result.stdout.lower()


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell operator wrapper is Windows-only")
def test_powershell_quoting_and_path_normalization(tmp_path: Path):
    output_dir = tmp_path / "phase one"
    manual = MARKETPLACE_FIXTURES / "ebay_terapeak_import.csv"
    result = _run_operator(
        "-OutputDirectory",
        str(output_dir),
        "-MarketplaceTrendImport",
        str(manual),
        "-MaxCandidates",
        "2",
    )
    assert result.returncode == 0, result.stderr
    summary = _summary_from_output(result.stdout)
    assert summary["evidence_mode"] == "manual_import"
    report = json.loads((output_dir / "marketplace_trend" / "marketplace_trend_report.json").read_text(encoding="utf-8"))
    assert report["evidence_mode"] == "manual_import"


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell operator wrapper is Windows-only")
def test_manual_import_mode_classifies_evidence(tmp_path: Path):
    output_dir = tmp_path / "manual"
    manual = MARKETPLACE_FIXTURES / "ebay_terapeak_import.csv"
    result = _run_operator("-OutputDirectory", str(output_dir), "-MarketplaceTrendImport", str(manual))
    assert result.returncode == 0, result.stderr
    summary = _summary_from_output(result.stdout)
    assert summary["evidence_mode"] == "manual_import"
