"""Bounded host-metadata probes for promotion rehearsal.

Protects Windows (and other) runs from unbounded platform.platform()/WMI
stalls while keeping runtime evidence truthful: collected | timed_out |
unavailable — never a fabricated ready/passed host-metadata status.
"""

from __future__ import annotations

import ast
import json
import time
from pathlib import Path

import pytest

from backend.deployment import promotion_rehearsal as rehearsal
from backend.deployment.promotion_rehearsal import (
    HOST_METADATA_STATUSES,
    collect_host_platform_metadata,
    execute_promotion_rehearsal,
    get_runtime_versions,
)


def test_promotion_rehearsal_source_avoids_unbounded_platform_platform() -> None:
    """Call path isolation: rehearsal must not invoke platform.platform()."""
    source_path = Path(rehearsal.__file__).resolve()
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    banned: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in {"platform", "processor", "uname"}:
            if isinstance(func.value, ast.Name) and func.value.id == "platform":
                banned.append((node.lineno, func.attr))
    assert banned == [], f"unbounded platform probe call(s) remain: {banned}"


def test_collect_host_platform_metadata_collected_is_deterministic() -> None:
    fixed = {
        "system": "Linux",
        "release": "6.1.0-test",
        "machine": "x86_64",
        "platform": "Linux-6.1.0-test-x86_64",
    }
    first = collect_host_platform_metadata(collector=lambda: fixed)
    second = collect_host_platform_metadata(collector=lambda: dict(fixed))
    assert first == second
    assert first["status"] == "collected"
    assert first["platform"] == "Linux-6.1.0-test-x86_64"
    assert first["detail"] is None
    assert first["status"] in HOST_METADATA_STATUSES
    assert first["status"] != "passed"


def test_stalled_host_metadata_probe_times_out_without_hanging() -> None:
    def stall() -> dict[str, str]:
        time.sleep(30)
        return {"system": "never", "release": "", "machine": "", "platform": "never"}

    started = time.monotonic()
    result = collect_host_platform_metadata(timeout_s=0.2, collector=stall)
    elapsed = time.monotonic() - started
    assert result["status"] == "timed_out"
    assert result["platform"] is None
    assert result["system"] is None
    assert "host_metadata_probe_exceeded" in str(result["detail"])
    assert elapsed < 5.0, f"probe wall time not bounded: {elapsed:.2f}s"


def test_raising_host_metadata_probe_is_unavailable_not_collected() -> None:
    def boom() -> dict[str, str]:
        raise RuntimeError("wmi_unavailable")

    result = collect_host_platform_metadata(timeout_s=1.0, collector=boom)
    assert result["status"] == "unavailable"
    assert result["platform"] is None
    assert result["detail"] == "host_metadata_probe_failed"


def test_empty_host_metadata_probe_is_unavailable() -> None:
    result = collect_host_platform_metadata(collector=lambda: {})
    assert result["status"] == "unavailable"
    assert result["platform"] is None
    assert result["detail"] == "host_metadata_empty"


def test_get_runtime_versions_surfaces_timed_out_host_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def stall() -> dict[str, str]:
        time.sleep(30)
        return {"system": "x", "release": "", "machine": "", "platform": "x"}

    monkeypatch.setattr(rehearsal.shutil, "which", lambda _name: None)
    started = time.monotonic()
    runtime = get_runtime_versions(
        host_metadata_timeout_s=0.2,
        host_metadata_collector=stall,
    )
    elapsed = time.monotonic() - started
    assert elapsed < 5.0
    assert runtime["platform"] is None
    assert runtime["host_metadata"]["status"] == "timed_out"
    assert runtime["host_metadata"]["status"] != "passed"
    assert runtime["host_metadata"]["status"] != "collected"


def test_stalled_probe_cannot_create_false_ready_promotion_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Timed-out host metadata must not fabricate collected/passed evidence,
    and must not leave readiness_state looking host-ready from that field."""

    def stall() -> dict[str, str]:
        time.sleep(30)
        return {
            "system": "Windows",
            "release": "10",
            "machine": "AMD64",
            "platform": "Windows-10-AMD64",
        }

    monkeypatch.setattr(
        rehearsal,
        "get_runtime_versions",
        lambda: get_runtime_versions(
            host_metadata_timeout_s=0.2,
            host_metadata_collector=stall,
        ),
    )
    # Keep the rehearsal offline and deterministic for non-runtime authorities.
    monkeypatch.setattr(
        rehearsal,
        "check_container_static_hardening",
        lambda *_a, **_k: {
            "status": "passed",
            "non_root_user": True,
            "healthcheck_present": True,
            "stopsignal_present": True,
            "port_3000": True,
        },
    )
    monkeypatch.setattr(
        rehearsal,
        "inspect_coderos_status",
        lambda *, environ: {"status": "unavailable", "runtime_imports_allowed": False},
    )
    monkeypatch.setattr(
        rehearsal,
        "run_all_diagnostics",
        lambda **_k: {
            "summary": {"status": "unavailable", "detected_issues": 0, "total_checks": 0},
            "diagnostics": [],
        },
    )
    monkeypatch.setattr(rehearsal, "_phase1_summary", lambda _environ: {"status": "unavailable"})
    monkeypatch.setattr(
        rehearsal,
        "_operator_stack_evidence",
        lambda **_kwargs: {"status": "unavailable"},
    )
    monkeypatch.setattr(rehearsal, "_event_read_path_evidence", lambda _environ: {"status": "unavailable"})
    monkeypatch.setattr(
        rehearsal,
        "_rollback_evidence",
        lambda _repository: {"status": "unavailable"},
    )

    started = time.monotonic()
    bundle = execute_promotion_rehearsal(
        environment="local_dry_run",
        environ={},
        ci_override={
            "ci_status": "ci_unavailable",
            "total_steps": 0,
            "runners_active": 0,
            "logs_available": False,
        },
        harness_results={
            "status": "unavailable",
            "evidence_classification": "simulated_or_planned",
            "paths_executed": 0,
            "all_paths_passed": False,
            "bit_identity_confirmed": False,
        },
    )
    elapsed = time.monotonic() - started
    assert elapsed < 10.0, f"rehearsal hung on stalled probe: {elapsed:.2f}s"

    runtime = bundle.runtime
    host = runtime["host_metadata"]
    assert host["status"] == "timed_out"
    assert host["platform"] is None
    assert host["status"] not in {"passed", "collected"}
    assert runtime["platform"] is None
    # Host metadata is not promotion-ready evidence; timed_out must not
    # upgrade readiness to passed.
    assert bundle.readiness_state != "passed"
    payload = bundle.to_dict()
    assert "timed_out" in json.dumps(payload["runtime"])


def test_fixed_runtime_inputs_yield_stable_host_metadata_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed = {
        "system": "Linux",
        "release": "0.0.0",
        "machine": "x86_64",
        "platform": "Linux-0.0.0-x86_64",
    }
    monkeypatch.setattr(rehearsal.shutil, "which", lambda _name: None)
    a = get_runtime_versions(host_metadata_collector=lambda: fixed)
    b = get_runtime_versions(host_metadata_collector=lambda: dict(fixed))
    assert a["host_metadata"] == b["host_metadata"]
    assert a["platform"] == b["platform"] == "Linux-0.0.0-x86_64"
    assert a["node"] == b["node"] == "unavailable"
    assert a["docker"] == b["docker"] == "unavailable"
