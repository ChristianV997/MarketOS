"""Windows operator workflow: path safety, scenario pack, no live mutation."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "scripts/operators/windows_operator_workflow.py"
PS1 = ROOT / "scripts/operators/Invoke-MarketOSOperator.ps1"
SCENARIOS = ROOT / "tests/fixtures/windows_operator/scenarios"


def _run(*args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=check,
    )


def _payload(proc: subprocess.CompletedProcess[str]) -> dict:
    return json.loads(proc.stdout)


def test_preflight_is_read_only_and_never_actual():
    proc = _run("preflight", "--json")
    body = _payload(proc)
    assert proc.returncode == 0
    assert body["read_only"] is True
    assert body["mutated"] is False
    assert body["network_calls"] is False
    assert body["evidence_class"] in {"fixture", "unavailable"}
    assert body["authorities"]["launch"] is False
    assert "actual" != body["evidence_class"]


def test_scenario_pack_verifies_all_five_without_network():
    proc = _run("scenario-pack", "--json")
    body = _payload(proc)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    details = body["details"]
    ids = [item["scenario_id"] for item in details["scenarios"]]
    assert ids == [
        "hydroponics",
        "smart-pet",
        "blocked-solar-4g-security",
        "rejected-commodity-electronics",
        "deferred-high-ticket",
    ]
    assert details["network_mutation"] is False
    assert details["secret_leakage"] is False
    assert details["replay"] == "byte_identical"
    gates = {item["scenario_id"]: item["promotion_gate"] for item in details["scenarios"]}
    assert gates["hydroponics"] == "hold"
    assert gates["blocked-solar-4g-security"] == "blocked"
    assert gates["rejected-commodity-electronics"] == "reject"
    assert gates["deferred-high-ticket"] == "defer"


def test_replay_is_byte_identical():
    proc = _run("replay", "--packet", str(SCENARIOS / "hydroponics.json"))
    body = _payload(proc)
    assert proc.returncode == 0
    assert body["status"] == "byte_identical"


def test_live_flags_are_blocked():
    proc = _run("preflight", "--allow-network")
    body = _payload(proc)
    assert proc.returncode == 4
    assert body["evidence_class"] == "blocked"


def test_path_traversal_rejected(tmp_path: Path):
    proc = _run("inspect-evidence", "--path", "../secrets.json")
    assert proc.returncode == 2


def test_artifacts_output_rejected(tmp_path: Path):
    proc = _run(
        "client-safe-export",
        "--source",
        str(SCENARIOS / "hydroponics.json"),
        "--output",
        str(ROOT / "artifacts" / "operator-out"),
    )
    assert proc.returncode == 2


def test_secret_shaped_export_rejected(tmp_path: Path):
    secret_file = tmp_path / "secret.json"
    secret_file.write_text(json.dumps({"api_key": "sk-live-NOT-A-REAL-KEY-1234567890abcd"}), encoding="utf-8")
    out = tmp_path / "safe-out"
    proc = _run("client-safe-export", "--source", str(secret_file), "--output", str(out))
    assert proc.returncode == 4


def test_fixture_import_and_client_safe_export(tmp_path: Path):
    out = tmp_path / "safe-out"
    proc = _run(
        "fixture-import",
        "--source",
        str(SCENARIOS / "smart-pet.json"),
        "--output",
        str(out),
    )
    body = _payload(proc)
    assert proc.returncode == 0
    assert body["evidence_class"] == "fixture"
    copied = out / "smart-pet.json"
    assert copied.is_file()
    export = _run("client-safe-export", "--source", str(copied), "--output", str(out / "export"))
    exported = _payload(export)
    assert export.returncode == 0
    assert exported["details"]["destination"].endswith("client_safe_export.json")


def test_supplier_import_is_simulated_not_actual(tmp_path: Path):
    src = ROOT / "tests/fixtures/supplier_feasibility/cj_manual_import.csv"
    if not src.is_file():
        pytest.skip("cj manual import fixture missing")
    proc = _run("supplier-import", "--source", str(src), "--output", str(tmp_path / "sim"))
    body = _payload(proc)
    assert proc.returncode == 0
    assert body["evidence_class"] == "simulated"


def test_start_local_does_not_spawn_servers():
    proc = _run("start-local")
    body = _payload(proc)
    assert proc.returncode == 0
    assert body["evidence_class"] == "not_run"
    assert "uvicorn" in body["details"]["api"]


def test_staging_default_is_not_run():
    proc = _run("staging-acceptance")
    body = _payload(proc)
    assert proc.returncode == 0
    assert body["evidence_class"] == "not_run"


def test_staging_base_url_blocked_without_policy():
    proc = _run("staging-acceptance", "--base-url", "https://example.invalid")
    assert proc.returncode == 4


def test_batch_manifest_validates_without_invoking_cycle():
    proc = _run("batch-manifest", "--manifest", str(ROOT / "tests/fixtures/windows_operator/batch_manifest.json"))
    body = _payload(proc)
    assert proc.returncode == 0
    assert body["details"]["job_count"] == 2


def test_product_validation_is_fixture_or_unavailable():
    proc = _run("product-validation", "--json")
    body = _payload(proc)
    assert proc.returncode in {0, 3}
    assert body["evidence_class"] in {"fixture", "unavailable"}


def test_commerce_cycle_is_fixture_or_unavailable():
    fixture = ROOT / "tests/fixtures/commerce_mvp/public_signals.json"
    proc = _run("commerce-cycle", "--fixture", str(fixture))
    body = _payload(proc)
    assert proc.returncode in {0, 3}
    assert body["evidence_class"] in {"fixture", "unavailable"}
    if body["details"]["mvp_slice"]["available"]:
        assert body["details"]["mvp_slice"]["exit_code"] == 0
    assert body["details"]["operations_cycle"] in {"not_run", "present_not_invoked_default"}


def test_phase_readiness_unavailable_without_scipy_is_truthful():
    proc = _run("phase-readiness")
    body = _payload(proc)
    assert proc.returncode in {0, 3}
    assert body["evidence_class"] in {"fixture", "unavailable"}


def test_powershell_wrapper_rejects_live_flags_and_uses_literal_paths():
    text = PS1.read_text(encoding="utf-8")
    assert "LiteralPath" in text
    assert "blocked live/network/provider/start flag" in text
    assert "Invoke-Expression" not in text
    assert "iex " not in text.lower()
    assert "AllowNetwork" in text
    for token in ("curl ", "Invoke-WebRequest", "Start-Process uvicorn"):
        assert token not in text


def test_powershell_scripts_parse_as_balanced_source():
    for path in (
        PS1,
        ROOT / "scripts/operators/run_dry_run_scenario_pack.ps1",
        ROOT / "scripts/operators/Invoke-StagingAcceptance.ps1",
    ):
        source = path.read_text(encoding="utf-8")
        assert source.count("{") == source.count("}")
        assert "#requires -Version 5.1" in source


def test_coderos_probe_plan_only():
    proc = _run("coderos-probe")
    body = _payload(proc)
    assert proc.returncode in {0, 3}
    if proc.returncode == 0:
        assert body["details"]["mode"] == "plan_only"
        assert body["evidence_class"] in {"not_run", "fixture"}


def test_unsupported_scenario_schema_rejected(tmp_path: Path):
    bad = tmp_path / "broken"
    bad.mkdir()
    (bad / "hydroponics.json").write_text(
        json.dumps({"schema_version": "nope", "scenario_id": "hydroponics", "stages": {}}),
        encoding="utf-8",
    )
    proc = _run("scenario-pack", "--pack-dir", str(bad))
    assert proc.returncode == 2
