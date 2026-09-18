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
    assert summary["overall_classification"] == "fixture"
    assert summary["overall_evidence_class"] == "fixture"
    assert summary["authoritative"] is False
    assert summary["fixture_only"] is True
    assert summary["live_validated"] is False
    assert summary["evidence_authority"] == "offline_planning_only"
    assert summary["lane_id"] == "WINDOWS-FIRST-PHASE-EVIDENCE-PACKET-01"
    assert summary["schema"] == "MarketOS.FirstPhaseOperatorSummary.v1"
    assert summary["execution_evidence"]["schema"] == "MarketOS.FirstPhaseExecutionEvidence.v1"
    assert summary["execution_evidence"]["run_mode"] == "fixture_demo"
    assert summary["execution_evidence"]["evidence_label"] == "fixture"
    assert summary["fingerprint"]
    assert summary["fingerprint"] == summary["execution_evidence"]["fingerprint"]
    assert summary["read_only"] is True
    assert summary["network_calls"] is False
    assert summary["mutated"] is False
    assert summary["output_directory"] is None
    assert summary["python_command"]
    assert [stage["classification"] for stage in summary["stages"]] == ["fixture"] * 8
    assert [stage["evidence_class"] for stage in summary["stages"]] == ["fixture"] * 8
    assert all(stage["status"] == "completed" for stage in summary["stages"])
    assert summary["decision_packet"]["present"] is True
    assert summary["decision_packet"]["operations_cycle"] == "not_run"
    assert summary["governor_result"]["present"] is True
    assert summary["trustos_result"]["present"] is True
    serialized = json.dumps(summary)
    assert '"classification":"actual"' not in serialized.replace(" ", "")
    assert '"evidence_class":"actual"' not in serialized.replace(" ", "")
    assert summary["stages"][5]["authority"] == "delegated_governor_cli"
    assert summary["stages"][6]["authority"] == "delegated_trustos_cli"


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
    manifest = output_dir / "first_phase_execution_evidence.json"
    assert manifest.is_file()
    manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    assert manifest_data["fingerprint"] == summary["fingerprint"]
    report = json.loads(marketplace.read_text(encoding="utf-8"))
    assert report["candidate_count"] <= 2


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell operator wrapper is Windows-only")
def test_missing_python_exits_with_unavailable_code(tmp_path: Path):
    missing = tmp_path / "missing-python.exe"
    result = _run_operator("-PythonPath", str(missing))
    assert result.returncode == 3
    assert "python interpreter not found" in result.stderr
    summary = _summary_from_output(result.stdout)
    assert summary["overall_evidence_class"] == "unavailable"
    assert summary["stages"][0]["classification"] == "unavailable"


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell operator wrapper is Windows-only")
def test_malformed_input_is_rejected_before_stages(tmp_path: Path):
    missing = tmp_path / "does-not-exist.csv"
    result = _run_operator("-MarketplaceTrendImport", str(missing))
    assert result.returncode == 2
    assert "does not exist" in result.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell operator wrapper is Windows-only")
def test_blocked_live_flags_are_rejected():
    for flag in ("-AllowNetwork", "-ClaimLiveExecution", "-LiveValidated"):
        result = _run_operator(flag)
        assert result.returncode == 4, flag
        assert "blocked live/network/provider/model flag" in result.stderr
        summary = _summary_from_output(result.stdout)
        assert summary["overall_evidence_class"] == "blocked"
        assert summary["stages"][0]["classification"] == "blocked"


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
    assert summary["stages"][-1]["id"] == "commerce_mvp"
    assert summary["stages"][-1]["classification"] == "not_run"
    assert any(stage["classification"] == "not_run" for stage in summary["stages"])
    assert summary["overall_classification"] == "failed"
    assert summary["overall_evidence_class"] == "failed"


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell operator wrapper is Windows-only")
def test_repeated_invocation_is_deterministic():
    first = _run_operator("-MaxCandidates", "2")
    second = _run_operator("-MaxCandidates", "2")
    assert first.returncode == 0 and second.returncode == 0
    summary_first = _summary_from_output(first.stdout)
    summary_second = _summary_from_output(second.stdout)
    for key in ("stages", "evidence_mode", "overall_classification", "overall_evidence_class", "authoritative", "fixture_only"):
        assert summary_first[key] == summary_second[key]
    assert summary_first["python_command"] == summary_second["python_command"]


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell operator wrapper is Windows-only")
def test_stable_summary_fingerprint_matches_across_runs():
    first = _summary_from_output(_run_operator("-MaxCandidates", "2").stdout)
    second = _summary_from_output(_run_operator("-MaxCandidates", "2").stdout)
    fingerprint_keys = (
        "authoritative",
        "evidence_authority",
        "evidence_mode",
        "execution_evidence",
        "fixture_only",
        "fingerprint",
        "lane_id",
        "live_validated",
        "max_candidates",
        "max_sources_per_candidate",
        "mutated",
        "network_calls",
        "overall_classification",
        "overall_evidence_class",
        "read_only",
        "stages",
        "governor_result",
        "trustos_result",
        "decision_packet",
    )
    assert {key: first[key] for key in fingerprint_keys} == {key: second[key] for key in fingerprint_keys}


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell operator wrapper is Windows-only")
def test_output_traversal_paths_are_rejected(tmp_path: Path):
    traversal = tmp_path / ".." / "escape-out"
    result = _run_operator("-OutputDirectory", str(traversal))
    assert result.returncode == 2
    assert "traversal" in result.stderr.lower()


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
    assert summary["overall_evidence_class"] == "simulated"
    assert all(stage["evidence_class"] == "simulated" for stage in summary["stages"] if stage["classification"] != "not_run")
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
    assert summary["overall_evidence_class"] == "simulated"
    assert all(stage["evidence_class"] == "simulated" for stage in summary["stages"] if stage["classification"] != "not_run")


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell operator wrapper is Windows-only")
def test_unknown_flags_are_rejected_by_powershell():
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            "-TotallyUnknownFlag",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell operator wrapper is Windows-only")
def test_fixture_success_is_never_classified_as_actual_live_execution():
    summary = _summary_from_output(_run_operator("-MaxCandidates", "2").stdout)
    serialized = json.dumps(summary)
    assert '"classification":"actual"' not in serialized.replace(" ", "")
    assert '"evidence_class":"actual"' not in serialized.replace(" ", "")
    assert summary["overall_classification"] == "fixture"
    assert summary["overall_evidence_class"] == "fixture"
    assert summary["fixture_only"] is True
    assert summary["live_validated"] is False
    assert summary["authoritative"] is False


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell operator wrapper is Windows-only")
def test_mixed_unavailable_stage_prevents_fixture_success_claim(tmp_path: Path):
    missing = tmp_path / "missing-python.exe"
    result = _run_operator("-PythonPath", str(missing))
    assert result.returncode == 3
    summary = _summary_from_output(result.stdout)
    assert summary["overall_evidence_class"] == "unavailable"
    assert summary["overall_classification"] == "unavailable"
    assert summary["fixture_only"] is True
    assert summary["live_validated"] is False
    assert summary["overall_evidence_class"] != "fixture"
    assert summary["overall_evidence_class"] != "actual"


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell operator wrapper is Windows-only")
def test_stage_failure_leaves_decision_packet_absent(tmp_path: Path):
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{not-json", encoding="utf-8")
    summary = _summary_from_output(_run_operator("-MarketplaceTrendSeed", str(bad_json)).stdout)
    assert summary["decision_packet"]["present"] is False
    assert summary["governor_result"]["present"] is False
    assert summary["trustos_result"]["present"] is False


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell operator wrapper is Windows-only")
def test_execution_evidence_manifest_fields_are_bounded():
    summary = _summary_from_output(_run_operator("-MaxCandidates", "2").stdout)
    stage = summary["stages"][0]
    for key in ("id", "status", "classification", "evidence_class", "evidence_label", "input_fixture_identity", "provenance", "freshness", "authority"):
        assert key in stage
    assert stage["input_fixture_identity"] == "builtin_fixture_demo"
    assert summary["execution_evidence"]["freshness"] == "not_observed"
    assert summary["execution_evidence"]["provenance"] == "offline_composed_cli"


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell operator wrapper is Windows-only")
def test_fixture_only_summary_never_contradicts_live_authority():
    summary = _summary_from_output(_run_operator("-MaxCandidates", "2").stdout)
    assert summary["fixture_only"] is True
    assert summary["live_validated"] is False
    assert summary["authoritative"] is False
    assert summary["overall_evidence_class"] in {"fixture", "simulated", "failed", "blocked", "unavailable", "not_run"}
    assert summary["overall_evidence_class"] not in {"actual"}
    assert summary["overall_classification"] not in {"actual"}
