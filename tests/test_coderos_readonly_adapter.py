"""Tests for backend.adapters.coderos_readonly -- the thin, read-only,
plan-only-by-default CoderOS capability adapter.

Most negative/edge-case paths are exercised by monkeypatching
subprocess.run directly (deterministic, platform-independent, and avoids
depending on a real CoderOS install, which does not exist in this
environment). One genuine end-to-end test uses a real, tiny local script
to prove the actual subprocess path -- argv construction and
shell=False -- truly works, not just against a mock.
"""
from __future__ import annotations

import ast
import inspect
import json
import os
import stat
import subprocess

import pytest

from backend.adapters import coderos_readonly as adapter


# --- helpers -----------------------------------------------------------------


def _patch_run(monkeypatch, *, returncode=0, stdout="", stderr="", raise_exc=None):
    calls = []

    def _fake_run(argv, **kwargs):
        calls.append((list(argv), kwargs))
        if raise_exc is not None:
            raise raise_exc
        return subprocess.CompletedProcess(argv, returncode, stdout, stderr)

    monkeypatch.setattr(adapter.subprocess, "run", _fake_run)
    return calls


def _probe_config(tmp_path, *, mode="probe", executable="coderos", **kwargs):
    (tmp_path / executable).touch()
    return adapter.CoderOSAdapterConfig(coderos_root=str(tmp_path), executable=executable, mode=mode, **kwargs)


# --- plan-only default / explicit probe opt-in -------------------------------


def test_plan_only_is_the_default_mode():
    config = adapter.CoderOSAdapterConfig()
    assert config.mode == "plan_only"


def test_plan_only_default_never_calls_subprocess(monkeypatch, tmp_path):
    def _explode(*args, **kwargs):
        raise AssertionError("subprocess.run must not be called in plan_only mode")

    monkeypatch.setattr(adapter.subprocess, "run", _explode)
    config = adapter.CoderOSAdapterConfig(coderos_root=str(tmp_path))
    report = adapter.probe(config)
    assert report.probe_result.state == "not_run"
    assert report.planned_action.would_execute is False


def test_explicit_probe_opt_in_reaches_subprocess(monkeypatch, tmp_path):
    calls = _patch_run(monkeypatch, returncode=0, stdout=json.dumps({"capabilities": []}))
    config = _probe_config(tmp_path, mode="probe")
    report = adapter.probe(config)
    assert len(calls) == 1
    assert report.probe_result.state == "available"


# --- argv construction / shell=False -----------------------------------------


def test_correct_argv_construction_and_shell_false_mocked(monkeypatch, tmp_path):
    calls = _patch_run(monkeypatch, returncode=0, stdout=json.dumps({"capabilities": []}))
    config = _probe_config(tmp_path, mode="probe", probe_args=("capabilities", "--json"))
    adapter.probe(config)
    argv, kwargs = calls[0]
    assert argv[0].endswith("coderos")
    assert argv[1:] == ["capabilities", "--json"]
    assert kwargs["shell"] is False
    assert kwargs["capture_output"] is True
    assert kwargs["timeout"] == config.timeout_s
    assert kwargs["cwd"] == str((tmp_path).resolve())


def test_real_subprocess_end_to_end_argv_and_output(tmp_path):
    """No mock: a genuine local script proves the real subprocess path
    (argv list, shell=False) actually works, not just against a stub."""
    if os.name == "nt":
        pytest.skip("Unix shebang fixture is unavailable on Windows")
    script = tmp_path / "fake_coderos"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "assert sys.argv[1:] == ['capabilities', '--json']\n"
        "print(json.dumps({'capabilities': [{'capability_id': 'cap-1', 'name': 'Read Files', "
        "'category': 'filesystem', 'read_only': True, 'description': 'test'}]}))\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    config = adapter.CoderOSAdapterConfig(coderos_root=str(tmp_path), executable="fake_coderos", mode="probe")
    report = adapter.probe(config)
    assert report.probe_result.state == "available"
    assert report.probe_result.exit_code == 0
    assert len(report.probe_result.capabilities) == 1
    assert report.probe_result.capabilities[0].capability_id == "cap-1"
    assert report.probe_result.capabilities[0].read_only is True


# --- timeout / oversized output / missing path / missing executable ---------


def test_probe_timeout_is_reported_and_no_raw_output_retained(monkeypatch, tmp_path):
    _patch_run(monkeypatch, raise_exc=subprocess.TimeoutExpired(cmd=["coderos"], timeout=5.0))
    config = _probe_config(tmp_path, mode="probe")
    report = adapter.probe(config)
    assert report.probe_result.state == "timed_out"
    assert report.probe_result.capabilities == ()


def test_oversized_output_is_discarded(monkeypatch, tmp_path):
    huge = "x" * 200
    _patch_run(monkeypatch, returncode=0, stdout=huge)
    config = _probe_config(tmp_path, mode="probe", max_output_bytes=100)
    report = adapter.probe(config)
    assert report.probe_result.state == "malformed"
    assert report.probe_result.capabilities == ()


def test_missing_coderos_root_is_unavailable(tmp_path):
    missing = tmp_path / "does-not-exist"
    config = adapter.CoderOSAdapterConfig(coderos_root=str(missing), mode="probe")
    report = adapter.probe(config)
    assert report.probe_result.state == "unavailable"


def test_missing_executable_is_unavailable(tmp_path):
    config = adapter.CoderOSAdapterConfig(coderos_root=str(tmp_path), executable="nonexistent-binary", mode="probe")
    report = adapter.probe(config)
    assert report.probe_result.state == "unavailable"


def test_executable_escaping_root_is_blocked(tmp_path):
    config = adapter.CoderOSAdapterConfig(coderos_root=str(tmp_path), executable="../escape", mode="probe")
    report = adapter.probe(config)
    assert report.probe_result.state == "blocked"


def test_absolute_executable_escaping_root_is_blocked(tmp_path):
    outside = tmp_path.parent / "outside-coderos"
    outside.touch()
    config = adapter.CoderOSAdapterConfig(
        coderos_root=str(tmp_path), executable=str(outside), mode="probe"
    )
    report = adapter.probe(config)
    assert report.probe_result.state == "blocked"


# --- malformed JSON / nonzero exit --------------------------------------------


def test_malformed_json_output_is_reported(monkeypatch, tmp_path):
    _patch_run(monkeypatch, returncode=0, stdout="{not valid json")
    config = _probe_config(tmp_path, mode="probe")
    report = adapter.probe(config)
    assert report.probe_result.state == "malformed"


def test_nonzero_exit_is_blocked_and_output_discarded(monkeypatch, tmp_path):
    _patch_run(monkeypatch, returncode=1, stdout=json.dumps({"capabilities": []}), stderr="boom")
    config = _probe_config(tmp_path, mode="probe")
    report = adapter.probe(config)
    assert report.probe_result.state == "blocked"
    assert report.probe_result.exit_code == 1
    assert report.probe_result.capabilities == ()


def test_secret_shaped_output_is_rejected_not_kept(monkeypatch, tmp_path):
    payload = json.dumps({"capabilities": [], "api_key": "sk-test-abcdefghijklmnopqrstuvwxyz"})
    _patch_run(monkeypatch, returncode=0, stdout=payload)
    config = _probe_config(tmp_path, mode="probe")
    report = adapter.probe(config)
    assert report.probe_result.state == "blocked"
    assert "sk-test" not in str(report.to_dict())


# --- sanitized capability extraction ------------------------------------------


def test_sanitized_capability_extraction_skips_incomplete_entries(monkeypatch, tmp_path):
    payload = json.dumps({
        "capabilities": [
            {"capability_id": "cap-1", "name": "Read Files", "category": "filesystem", "read_only": True},
            {"name": "missing id", "category": "x", "read_only": True},
            {"capability_id": "cap-2", "name": "List Repos", "read_only": False},
            "not-a-dict",
        ]
    })
    _patch_run(monkeypatch, returncode=0, stdout=payload)
    config = _probe_config(tmp_path, mode="probe")
    report = adapter.probe(config)
    assert report.probe_result.state == "available"
    ids = {item.capability_id for item in report.probe_result.capabilities}
    assert ids == {"cap-1", "cap-2"}
    assert len(report.probe_result.warnings) >= 2


# --- no raw stdout/stderr in result -------------------------------------------


def test_no_raw_stdout_or_stderr_ever_in_result(monkeypatch, tmp_path):
    marker_out, marker_err = "TOTALLY_UNIQUE_STDOUT_MARKER", "TOTALLY_UNIQUE_STDERR_MARKER"
    _patch_run(monkeypatch, returncode=0,
               stdout=json.dumps({"capabilities": []}) + marker_out, stderr=marker_err)
    config = _probe_config(tmp_path, mode="probe")
    report = adapter.probe(config)
    # This payload is actually malformed (trailing marker breaks JSON), which
    # itself proves discard-on-malformed; also assert no raw text anywhere.
    blob = str(report.to_dict())
    assert marker_out not in blob
    assert marker_err not in blob


def test_safety_summary_asserts_no_raw_output_exposure(tmp_path):
    config = adapter.CoderOSAdapterConfig(coderos_root=str(tmp_path))
    report = adapter.probe(config)
    safety = report.safety_summary
    assert safety.raw_stdout_exposed is False
    assert safety.raw_stderr_exposed is False
    assert safety.read_only is True
    assert safety.fail_closed is True


# --- safety contract: no network / credentials / mutation / retry -----------


def test_safety_summary_full_contract(tmp_path):
    config = adapter.CoderOSAdapterConfig(coderos_root=str(tmp_path))
    safety = adapter.probe(config).safety_summary
    assert safety.network_calls is False
    assert safety.credentials_loaded is False
    assert safety.external_mutation is False
    assert safety.model_calls is False
    assert safety.provider_calls is False
    assert safety.sdk_used is False
    assert safety.artifact_writes is False
    assert safety.background_process is False
    assert safety.automatic_retry is False


def test_safety_summary_cannot_be_constructed_unsafe():
    with pytest.raises(ValueError):
        adapter.SafetySummary(
            read_only=True, network_calls=True, credentials_loaded=False, external_mutation=False,
            model_calls=False, provider_calls=False, sdk_used=False, raw_stdout_exposed=False,
            raw_stderr_exposed=False, artifact_writes=False, background_process=False,
            automatic_retry=False, fail_closed=True,
        )


def test_module_imports_no_network_or_sdk_modules():
    source = inspect.getsource(adapter)
    tree = ast.parse(source)
    imported_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.add(node.module.split(".")[0])
    forbidden = {"requests", "httpx", "urllib3", "socket", "aiohttp", "boto3", "openai", "anthropic"}
    assert imported_names.isdisjoint(forbidden)


def test_module_never_reads_environment_variables():
    """No os.environ / os.getenv calls anywhere -- this adapter takes all
    configuration explicitly via CoderOSAdapterConfig, never implicit
    credential-shaped environment lookups."""
    source = inspect.getsource(adapter)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in {"environ", "getenv"}:
            pytest.fail(f"unexpected environment access: {ast.dump(node)}")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getenv":
            pytest.fail("unexpected getenv() call")


def test_module_performs_no_filesystem_write_or_delete_calls():
    """Static check that this module contains no open(..., 'w'/'a'/'x')
    calls, os.remove, or shutil.rmtree anywhere in its source."""
    source = inspect.getsource(adapter)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name in {"remove", "unlink", "rmtree", "rmdir"}:
                pytest.fail(f"unexpected filesystem mutation call: {name}")
            if name == "open":
                for arg in list(node.args)[1:2] + [kw.value for kw in node.keywords if kw.arg == "mode"]:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and any(
                        flag in arg.value for flag in ("w", "a", "x")
                    ):
                        pytest.fail("unexpected write-mode open() call")


# --- no import-time execution -------------------------------------------------


def test_import_time_performs_no_subprocess_call(monkeypatch):
    def _explode(*args, **kwargs):
        raise AssertionError("subprocess.run must not be called merely by importing/reloading the module")

    monkeypatch.setattr(adapter.subprocess, "run", _explode)
    import importlib
    importlib.reload(adapter)


def test_constructing_config_alone_never_calls_subprocess(monkeypatch):
    def _explode(*args, **kwargs):
        raise AssertionError("constructing CoderOSAdapterConfig must not call subprocess.run")

    monkeypatch.setattr(adapter.subprocess, "run", _explode)
    adapter.CoderOSAdapterConfig(coderos_root="/nonexistent", mode="probe")
    adapter.health()


# --- deterministic output ------------------------------------------------------


def test_plan_only_output_is_deterministic(monkeypatch, tmp_path):
    monkeypatch.setattr(adapter.time, "time", lambda: 1000.0)
    config = adapter.CoderOSAdapterConfig(coderos_root=str(tmp_path))
    first = adapter.probe(config).to_dict()
    second = adapter.probe(config).to_dict()
    assert first == second


def test_probe_output_is_deterministic_given_identical_subprocess_result(monkeypatch, tmp_path):
    monkeypatch.setattr(adapter.time, "time", lambda: 2000.0)
    payload = json.dumps({"capabilities": [{"capability_id": "cap-1", "name": "X", "category": "y", "read_only": True}]})
    _patch_run(monkeypatch, returncode=0, stdout=payload)
    config = _probe_config(tmp_path, mode="probe")
    first = adapter.probe(config).to_dict()
    _patch_run(monkeypatch, returncode=0, stdout=payload)
    second = adapter.probe(config).to_dict()
    assert first == second


# --- config validation ---------------------------------------------------------


def test_invalid_mode_rejected():
    with pytest.raises(ValueError):
        adapter.CoderOSAdapterConfig(mode="not_a_real_mode")


def test_non_positive_timeout_rejected():
    with pytest.raises(ValueError):
        adapter.CoderOSAdapterConfig(timeout_s=0)


def test_non_positive_max_output_bytes_rejected():
    with pytest.raises(ValueError):
        adapter.CoderOSAdapterConfig(max_output_bytes=0)


# --- health() ------------------------------------------------------------------


def test_health_is_offline_and_unreachable():
    result = adapter.health()
    assert result["configured"] is True
    assert result["reachable"] is False
    assert "plan_only" in result["capabilities"]
