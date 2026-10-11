"""Windows operator workflow: path safety, scenario pack, no live mutation."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import scripts.operators.windows_operator_workflow as workflow

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


def test_nested_cli_timeout_is_reported_as_unavailable(monkeypatch):
    def _timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="python", timeout=60)

    monkeypatch.setattr(workflow.subprocess, "run", _timeout)
    result = workflow._run_cli("scripts/generate_product_validation_report.py", ["--json"])

    assert result == {
        "available": False,
        "exit_code": 3,
        "reason": "cli_timeout",
        "stdout": "",
    }


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


ABS_LEAK_CANARY = "PROBE-BODY-CANARY-7431"
SECRET_SHAPED_LEAF = "sk-liveSYNTHCANARY0123456789.json"


def _roots(tmp_path: Path) -> tuple[str, ...]:
    return (str(tmp_path), str(tmp_path.resolve()))


def _forbidden_variants(*values: str) -> list[str]:
    variants: list[str] = []
    for value in values:
        for variant in (value, value.replace("\\", "/"), json.dumps(value)[1:-1]):
            if variant and variant not in variants:
                variants.append(variant)
    return variants


def _assert_absent(text: str, *forbidden: str) -> None:
    # Assertion text names no canary: failures report only that a disclosure reached output.
    for needle in _forbidden_variants(*forbidden):
        assert needle not in text, "absolute path or canary reached operator output"


def _assert_no_disclosure(proc: subprocess.CompletedProcess[str], *forbidden: str) -> None:
    _assert_absent(proc.stdout + proc.stderr, *forbidden)


def test_inspect_reports_leaf_only_and_never_the_body(tmp_path: Path):
    evidence = tmp_path / "inspect-probe.json"
    evidence.write_text(json.dumps({"evidence_class": "fixture", "note": ABS_LEAK_CANARY}), encoding="utf-8")
    proc = _run("inspect-evidence", "--path", str(evidence))
    body = _payload(proc)
    assert proc.returncode == 0
    assert body["details"]["path"] == "inspect-probe.json"
    _assert_no_disclosure(proc, *_roots(tmp_path), ABS_LEAK_CANARY)


def test_inspect_redacts_secret_shaped_basename(tmp_path: Path):
    evidence = tmp_path / SECRET_SHAPED_LEAF
    evidence.write_text(json.dumps({"evidence_class": "fixture"}), encoding="utf-8")
    proc = _run("inspect-evidence", "--path", str(evidence))
    body = _payload(proc)
    assert proc.returncode == 0
    assert body["details"]["path"] == workflow.REDACTED_LEAF
    _assert_no_disclosure(proc, *_roots(tmp_path), SECRET_SHAPED_LEAF)


def test_missing_input_error_does_not_echo_directory(tmp_path: Path):
    missing = tmp_path / "absent-probe.json"
    proc = _run("inspect-evidence", "--path", str(missing))
    body = _payload(proc)
    assert proc.returncode == 2
    assert body["details"]["error"] == "evidence does not exist: absent-probe.json"
    _assert_no_disclosure(proc, *_roots(tmp_path))


def test_undecodable_input_returns_json_not_a_traceback(tmp_path: Path):
    binary = tmp_path / "binary-probe.json"
    binary.write_bytes(b"\xff\xfe" + ABS_LEAK_CANARY.encode("ascii"))
    proc = _run("inspect-evidence", "--path", str(binary))
    body = _payload(proc)
    assert proc.returncode == 2
    assert body["details"]["error"] == "input_unreadable_or_malformed"
    assert "Traceback" not in proc.stderr
    _assert_no_disclosure(proc, *_roots(tmp_path), str(ROOT), ABS_LEAK_CANARY)


def test_replay_redacts_secret_shaped_packet_name(tmp_path: Path):
    packet = tmp_path / SECRET_SHAPED_LEAF
    packet.write_text(json.dumps({"evidence_class": "fixture", "stages": {}}), encoding="utf-8")
    proc = _run("replay", "--packet", str(packet))
    body = _payload(proc)
    assert proc.returncode == 0
    assert body["details"]["path"] == workflow.REDACTED_LEAF
    _assert_no_disclosure(proc, *_roots(tmp_path), SECRET_SHAPED_LEAF)


def test_fixture_import_and_export_project_leaves_only(tmp_path: Path):
    src = tmp_path / "fixture-probe.json"
    src.write_text(json.dumps({"evidence_class": "fixture", "note": ABS_LEAK_CANARY}), encoding="utf-8")
    out = tmp_path / "out"
    imported = _run("fixture-import", "--source", str(src), "--output", str(out))
    assert imported.returncode == 0
    assert _payload(imported)["details"]["source"] == "fixture-probe.json"
    _assert_no_disclosure(imported, *_roots(tmp_path), ABS_LEAK_CANARY)

    exported = _run(
        "client-safe-export",
        "--source",
        str(out / "fixture-probe.json"),
        "--output",
        str(out / "export"),
    )
    body = _payload(exported)
    assert exported.returncode == 0
    assert body["details"]["source"] == "fixture-probe.json"
    assert body["details"]["destination"] == "client_safe_export.json"
    _assert_no_disclosure(exported, *_roots(tmp_path), ABS_LEAK_CANARY)


def test_client_safe_export_rejects_secret_shaped_leaf_without_echo(tmp_path: Path):
    src = tmp_path / SECRET_SHAPED_LEAF
    src.write_text(json.dumps({"evidence_class": "fixture"}), encoding="utf-8")
    proc = _run("client-safe-export", "--source", str(src), "--output", str(tmp_path / "export"))
    assert proc.returncode == 4
    _assert_no_disclosure(proc, *_roots(tmp_path), SECRET_SHAPED_LEAF)


def test_batch_manifest_projects_leaf_and_repo_relative_cli(tmp_path: Path):
    manifest = tmp_path / "batch-probe.json"
    manifest.write_text(json.dumps({"jobs": [{"id": 1}, {"id": 2}]}), encoding="utf-8")
    proc = _run("batch-manifest", "--manifest", str(manifest))
    body = _payload(proc)
    assert proc.returncode == 0
    assert body["details"]["manifest"] == "batch-probe.json"
    assert body["details"]["operations_cycle_cli"] == "scripts/run_commerce_operations_cycle.py"
    _assert_no_disclosure(proc, *_roots(tmp_path), str(ROOT))


def test_commerce_cycle_invalid_fixture_error_is_leaf_only(tmp_path: Path):
    fixture = tmp_path / "commerce-probe.json"
    fixture.write_text("{" + ABS_LEAK_CANARY, encoding="utf-8")
    proc = _run("commerce-cycle", "--fixture", str(fixture))
    body = _payload(proc)
    assert proc.returncode == 2
    assert body["details"]["error"] == "commerce fixture could not be read: commerce-probe.json"
    _assert_no_disclosure(proc, *_roots(tmp_path), ABS_LEAK_CANARY)


def test_scenario_pack_error_is_leaf_only(tmp_path: Path):
    pack = tmp_path / "pack-probe"
    pack.mkdir()
    (pack / "hydroponics.json").write_text(json.dumps([ABS_LEAK_CANARY]), encoding="utf-8")
    proc = _run("scenario-pack", "--pack-dir", str(pack))
    body = _payload(proc)
    assert proc.returncode == 2
    assert "hydroponics.json" in body["details"]["error"]
    _assert_no_disclosure(proc, *_roots(tmp_path), ABS_LEAK_CANARY)


def test_preflight_reports_repository_name_not_absolute_root():
    proc = _run("preflight", "--json")
    body = _payload(proc)
    assert body["details"]["repository"] == ROOT.name
    _assert_no_disclosure(proc, str(ROOT))


def test_coderos_probe_hides_user_home_and_repo_root():
    proc = _run("coderos-probe")
    assert proc.returncode in {0, 3}
    _assert_no_disclosure(proc, str(ROOT), "C:\\Users\\HP")


def test_error_path_writes_json_only_and_no_stderr(tmp_path: Path, capsys):
    missing = tmp_path / "absent-main-probe.json"
    code = workflow.main(["replay", "--packet", str(missing)])
    captured = capsys.readouterr()
    assert code == 2
    assert captured.err == ""
    _assert_absent(captured.out, *_roots(tmp_path))
    assert json.loads(captured.out)["details"]["error"].endswith("absent-main-probe.json")


def test_failed_nested_cli_output_is_suppressed(monkeypatch, tmp_path: Path):
    leaked = tmp_path / "nested-probe" / "tool.py"

    def _failing_cli(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=["python"],
            returncode=1,
            stdout=f'Traceback (most recent call last):\n  File "{leaked}", line 1\n{ABS_LEAK_CANARY}\n',
            stderr="",
        )

    monkeypatch.setattr(workflow.subprocess, "run", _failing_cli)
    payload = workflow.cmd_product_validation("", None)
    rendered = json.dumps(payload)
    assert payload["details"]["cli"]["reason"] == "cli_failed"
    assert payload["details"]["cli"]["stdout"] == ""
    _assert_absent(rendered, str(leaked), ABS_LEAK_CANARY)


def test_leaf_policy_keeps_ordinary_names_and_redacts_sensitive_ones(tmp_path: Path):
    for name in ("smart-pet.json", "cj_manual_import.csv", "tokenizer.json", "client_safe_export.json"):
        assert workflow.leaf_of(tmp_path / name) == name
    for name in ("secret.json", "api_key.json", SECRET_SHAPED_LEAF):
        assert workflow.leaf_of(tmp_path / name) == workflow.REDACTED_LEAF


def test_scrub_text_replaces_drive_and_unc_paths_but_not_urls():
    backslash = chr(92)
    drive_path = (
        "C:" + backslash + "Users" + backslash + "Example" + backslash + "Private Folder" + backslash + "good.json"
    )
    unc_path = backslash * 2 + "server" + backslash + "share" + backslash + "run.json"
    assert workflow.scrub_text(f"does not exist: {drive_path}") == "does not exist: good.json"
    assert workflow.scrub_text(f"see {unc_path}") == "see run.json"
    assert workflow.scrub_text("https://example.invalid/health") == "https://example.invalid/health"


def test_inspect_projection_is_path_independent(tmp_path: Path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    for folder in (first, second):
        folder.mkdir()
        (folder / "same-probe.json").write_text(json.dumps({"evidence_class": "fixture"}), encoding="utf-8")
    left = workflow.cmd_inspect(str(first / "same-probe.json"))
    right = workflow.cmd_inspect(str(second / "same-probe.json"))
    assert left["details"] == right["details"]
    assert left["fingerprint"] == right["fingerprint"]


def test_output_write_failure_emits_one_json_document(tmp_path: Path):
    evidence = tmp_path / "write-probe.json"
    evidence.write_text(json.dumps({"evidence_class": "fixture"}), encoding="utf-8")
    blocker = tmp_path / "blocker-file"
    blocker.write_text("not a directory", encoding="utf-8")
    proc = _run("inspect-evidence", "--path", str(evidence), "--output", str(blocker))
    body = _payload(proc)  # raises if stdout holds more than one JSON document
    assert proc.returncode == 2
    assert body["status"] == "input_unreadable_or_malformed"
    _assert_no_disclosure(proc, *_roots(tmp_path))


def test_successful_nested_cli_output_projects_fixed_token_and_no_body_disclosure(monkeypatch):
    def _successful_cli(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=["python"],
            returncode=0,
            stdout=f'{{"status": "ok", "secret_body": "{ABS_LEAK_CANARY}"}}\n',
            stderr="",
        )

    monkeypatch.setattr(workflow.subprocess, "run", _successful_cli)
    payload = workflow.cmd_product_validation("", None)
    rendered = json.dumps(payload)
    assert payload["details"]["cli"]["reason"] == "ok"
    assert payload["details"]["cli"]["stdout"] == "completed"
    _assert_absent(rendered, ABS_LEAK_CANARY)


def test_unrecognized_command_emits_json_without_echoing_caller_text():
    canary = "unrecognized-cmd-probe-9988"
    proc = _run(canary)
    assert proc.returncode == 2
    assert proc.stderr == ""
    body = _payload(proc)
    assert body["command"] == "invalid"
    assert body["exit_code"] == 2
    assert body["status"] == "unrecognized_command"
    assert body["details"]["error"] == "unrecognized_command"
    _assert_absent(proc.stdout + proc.stderr, canary)


def test_unrecognized_arguments_emit_json_without_echoing_caller_args():
    flag_canary = "--flag-probe-7766"
    val_canary = "val-probe-5544"
    proc = _run("preflight", flag_canary, val_canary)
    assert proc.returncode == 2
    assert proc.stderr == ""
    body = _payload(proc)
    assert body["command"] == "invalid"
    assert body["exit_code"] == 2
    assert body["status"] == "invalid_arguments"
    assert body["details"]["error"] == "invalid_arguments"
    _assert_absent(proc.stdout + proc.stderr, flag_canary, val_canary)


def test_scrub_text_handles_posix_paths_and_secret_leaves():
    posix_path = "/tmp/pytest-of-runner/pytest-0/test_output.json"
    posix_secret = "/home/runner/work/MarketOS/sk-live1234567890abcdef.json"
    assert workflow.scrub_text(f"path: {posix_path}") == "path: test_output.json"
    assert workflow.scrub_text(f"secret: {posix_secret}") == f"secret: {workflow.REDACTED_LEAF}"
    assert workflow.scrub_text("route /operator/first-phase is safe") == "route /operator/first-phase is safe"
