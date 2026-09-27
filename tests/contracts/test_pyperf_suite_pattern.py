"""Contract tests for the src-pyperf JSON 1.0 copy-pattern.

No pyperf dependency. Samples are fixtures. Network and host probes stay off.
"""
from __future__ import annotations

import ast
import json
import math
from pathlib import Path

import pytest

from scripts.benchmarks.perf_engine import (
    JSON_VERSION,
    PerfEngineError,
    REGISTRY_RECORDED_SHA,
    SOURCE_ID,
    UPSTREAM_COMMIT_SHA,
    UPSTREAM_LICENSE,
    UPSTREAM_TAG,
    dump_suite,
    run_benchmark,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENGINE = _REPO_ROOT / "scripts" / "benchmarks" / "perf_engine.py"
_PRODUCTION_ROOTS = ("api", "backend", "core", "marketos", "orchestrator", "services")


def test_run_benchmark_emits_pyperf_json_1_0_shape() -> None:
    suite = run_benchmark("timeit-list-multiply", (0.001, 0.0012, 0.0009), unit="second")
    assert suite["version"] == JSON_VERSION == "1.0"
    assert suite["metadata"]["source_id"] == SOURCE_ID
    assert suite["metadata"]["upstream_commit_sha"] == UPSTREAM_COMMIT_SHA
    assert suite["metadata"]["upstream_tag"] == UPSTREAM_TAG
    assert suite["metadata"]["license"] == UPSTREAM_LICENSE
    assert suite["metadata"]["network_calls"] is False
    assert suite["metadata"]["collect_host_metadata"] is False
    bench = suite["benchmarks"][0]
    assert bench["metadata"]["name"] == "timeit-list-multiply"
    assert bench["metadata"]["unit"] == "second"
    assert bench["runs"][0]["values"] == [0.001, 0.0012, 0.0009]
    assert "hostname" not in bench["metadata"]
    dumped = json.loads(dump_suite(suite))
    assert dumped["version"] == "1.0"
    assert "suite_fingerprint" not in dumped
    assert dumped["benchmarks"][0]["runs"][0]["values"][0] == 0.001


def test_run_benchmark_is_deterministic() -> None:
    first = run_benchmark("stable", (0.2, 0.25))
    second = run_benchmark("stable", (0.2, 0.25))
    assert first["suite_fingerprint"] == second["suite_fingerprint"]
    assert len(first["suite_fingerprint"]) == 64


def test_run_benchmark_rejects_non_finite_and_non_positive_values() -> None:
    with pytest.raises(PerfEngineError):
        run_benchmark("bad", (math.nan,))
    with pytest.raises(PerfEngineError):
        run_benchmark("bad", (math.inf,))
    with pytest.raises(PerfEngineError):
        run_benchmark("bad", (0.0,))
    with pytest.raises(PerfEngineError):
        run_benchmark("bad", (-0.1,))
    with pytest.raises(PerfEngineError):
        run_benchmark("bad", ())


def test_run_benchmark_rejects_host_and_secret_metadata() -> None:
    with pytest.raises(PerfEngineError):
        run_benchmark("named", (0.1,), metadata={"hostname": "prod-box"})
    with pytest.raises(PerfEngineError):
        run_benchmark("named", (0.1,), metadata={"api_key": "not-a-secret-placeholder"})


def test_warmups_match_pyperf_loops_value_pairs() -> None:
    suite = run_benchmark("with-warmups", (0.4,), warmups=((2, 0.5),))
    assert suite["benchmarks"][0]["runs"][0]["warmups"] == [[2, 0.5]]
    with pytest.raises(PerfEngineError):
        run_benchmark("bad-warmup", (0.4,), warmups=((0, 0.5),))


def test_implementation_uses_verified_tag_not_stale_registry_sha() -> None:
    assert UPSTREAM_COMMIT_SHA == "c58426688e1a28b2519695a3869b98dc51f3a69d"
    assert UPSTREAM_COMMIT_SHA != REGISTRY_RECORDED_SHA
    assert len(UPSTREAM_COMMIT_SHA) == 40


def test_engine_does_not_import_pyperf_or_open_network() -> None:
    tree = ast.parse(_ENGINE.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module.split(".", 1)[0])
    forbidden = {
        "pyperf",
        "socket",
        "urllib",
        "http",
        "requests",
        "aiohttp",
        "subprocess",
        "ctypes",
    }
    assert forbidden.isdisjoint(imported), imported


def test_production_roots_do_not_import_perf_engine() -> None:
    needle = "scripts.benchmarks.perf_engine"
    violations: list[str] = []
    for root_name in _PRODUCTION_ROOTS:
        root = _REPO_ROOT / root_name
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if needle in text or "benchmarks.perf_engine" in text:
                violations.append(str(path.relative_to(_REPO_ROOT)))
    assert violations == []
