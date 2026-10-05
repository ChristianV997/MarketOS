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
    UPSTREAM_LICENSE_EVIDENCE,
    UPSTREAM_REPOSITORY,
    UPSTREAM_TAG,
    compare_suites,
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
    dumped_text = dump_suite(suite)
    dumped = json.loads(dumped_text)
    assert set(dumped) == {"version", "metadata", "benchmarks"}
    assert dumped["version"] == "1.0"
    assert "suite_fingerprint" not in dumped
    assert dumped["benchmarks"][0]["runs"][0]["values"][0] == 0.001


def test_run_benchmark_is_deterministic() -> None:
    first = run_benchmark(
        "stable", (0.2, 0.25), metadata={"scenario": "fixture", "tags": ["offline"]}
    )
    second = run_benchmark(
        "stable", (0.2, 0.25), metadata={"tags": ["offline"], "scenario": "fixture"}
    )
    assert first["suite_fingerprint"] == second["suite_fingerprint"]
    assert dump_suite(first) == dump_suite(second)
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


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(None, id="none"),
        pytest.param(True, id="boolean"),
        pytest.param("0.1", id="numeric-string"),
        pytest.param(10**1000, id="oversized-integer"),
    ],
)
def test_run_benchmark_rejects_malformed_sample_types(value: object) -> None:
    with pytest.raises(PerfEngineError):
        run_benchmark("bad", (value,))


@pytest.mark.parametrize("values", [None, "2", b"2", 2], ids=["none", "string", "bytes", "integer"])
def test_run_benchmark_rejects_non_sequence_samples(values: object) -> None:
    with pytest.raises(PerfEngineError):
        run_benchmark("bad", values)  # type: ignore[arg-type]


def test_run_benchmark_rejects_host_and_secret_metadata() -> None:
    with pytest.raises(PerfEngineError):
        run_benchmark("named", (0.1,), metadata={"hostname": "prod-box"})
    with pytest.raises(PerfEngineError):
        run_benchmark("named", (0.1,), metadata={"api_key": "not-a-secret-placeholder"})


@pytest.mark.parametrize(
    "key",
    [
        "host-name",
        "cpu-model-name",
        "python-executable",
        "machine-model",
        "host-id",
        "environment-variables",
        "api-key",
        "private-key",
    ],
)
def test_run_benchmark_rejects_normalized_host_and_secret_key_aliases(key: str) -> None:
    with pytest.raises(PerfEngineError):
        run_benchmark("named", (0.1,), metadata={key: "fixture-placeholder"})


@pytest.mark.parametrize(
    "metadata",
    [
        pytest.param({"custom": {"nested": "value"}}, id="nested-object"),
        pytest.param({"custom": None}, id="null-value"),
        pytest.param({"custom": ""}, id="empty-string"),
        pytest.param({"tags": ["all"]}, id="reserved-tag"),
        pytest.param({"loops": 0}, id="special-pyperf-loops"),
        pytest.param({"duration": -1.0}, id="special-pyperf-duration"),
        pytest.param({"Tags": ["offline"]}, id="case-mismatched-tags"),
        pytest.param({"name": "replacement"}, id="reserved-name"),
        pytest.param({"unit": "cycles"}, id="reserved-unit"),
    ],
)
def test_run_benchmark_rejects_malformed_or_reserved_metadata(metadata: dict) -> None:
    with pytest.raises(PerfEngineError):
        run_benchmark("named", (0.1,), metadata=metadata)


@pytest.mark.parametrize("unit", ["second", "byte", "integer"])
def test_run_benchmark_accepts_pyperf_units(unit: str) -> None:
    suite = run_benchmark("named", (0.1,), unit=unit)
    assert suite["benchmarks"][0]["metadata"]["unit"] == unit


def test_run_benchmark_rejects_unknown_pyperf_unit() -> None:
    with pytest.raises(PerfEngineError):
        run_benchmark("named", (0.1,), unit="cycles")


def test_warmups_match_pyperf_loops_value_pairs() -> None:
    suite = run_benchmark("with-warmups", (0.4,), warmups=((2, 0.5),))
    assert suite["benchmarks"][0]["runs"][0]["warmups"] == [[2, 0.5]]
    with pytest.raises(PerfEngineError):
        run_benchmark("bad-warmup", (0.4,), warmups=((0, 0.5),))


@pytest.mark.parametrize(
    "warmups",
    [
        pytest.param(((True, 0.5),), id="boolean-loops"),
        pytest.param(((1, "not-numeric"),), id="malformed-value"),
        pytest.param(((1, 10**1000),), id="oversized-value"),
        pytest.param(((1, math.inf),), id="non-finite-value"),
        pytest.param(0, id="non-sequence-container"),
    ],
)
def test_run_benchmark_rejects_malformed_warmups(warmups: tuple) -> None:
    with pytest.raises(PerfEngineError):
        run_benchmark("bad-warmup", (0.4,), warmups=warmups)


def test_implementation_uses_verified_tag_not_stale_registry_sha() -> None:
    assert UPSTREAM_COMMIT_SHA == "c58426688e1a28b2519695a3869b98dc51f3a69d"
    assert UPSTREAM_COMMIT_SHA != REGISTRY_RECORDED_SHA
    assert len(UPSTREAM_COMMIT_SHA) == 40


def test_upstream_pin_and_license_match_notice_and_manifest() -> None:
    assert UPSTREAM_TAG == "2.8.1"
    assert UPSTREAM_COMMIT_SHA == "c58426688e1a28b2519695a3869b98dc51f3a69d"
    assert UPSTREAM_LICENSE == "MIT"
    assert UPSTREAM_LICENSE_EVIDENCE == (
        f"{UPSTREAM_REPOSITORY}/blob/{UPSTREAM_COMMIT_SHA}/COPYING"
    )

    notices = (_REPO_ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert f"| pyperf | {UPSTREAM_TAG} (`{UPSTREAM_COMMIT_SHA}`) | MIT |" in notices
    assert "Copyright 2016, Red Hat, Inc. and Google Inc." in notices

    manifest = (_REPO_ROOT / "docs" / "oss" / "LICENSE_MANIFEST.yml").read_text(
        encoding="utf-8"
    )
    assert "  - name: pyperf\n    license: MIT\n    reviewed_ref: 2.8.1\n" in manifest
    assert f"Pin {UPSTREAM_COMMIT_SHA}. No upstream source vendored." in manifest


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
        "os",
        "platform",
        "sys",
        "time",
        "timeit",
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


def test_compare_suites_classifies_regression_improvement_and_noise() -> None:
    baseline = run_benchmark("parse-row", (2.0, 2.0), unit="second")
    same = run_benchmark("parse-row", (2.0, 2.0), unit="second")
    slower = run_benchmark("parse-row", (6.0, 6.0), unit="second")
    faster = run_benchmark("parse-row", (0.5, 0.5), unit="second")
    within = run_benchmark("parse-row", (4.0, 4.0), unit="second")
    assert compare_suites(baseline, same, threshold=2.0)["status"] == "pass"
    assert compare_suites(baseline, slower, threshold=2.0)["status"] == "regression"
    assert compare_suites(baseline, faster, threshold=2.0)["status"] == "improvement"
    # ratio == threshold is not yet a regression
    assert compare_suites(baseline, within, threshold=2.0)["status"] == "pass"


def test_compare_suites_is_deterministic_and_ignores_benchmark_order() -> None:
    first = {
        "version": "1.0",
        "metadata": {"hostname": "must-not-leak"},
        "benchmarks": [
            {"metadata": {"name": "b", "unit": "second"}, "runs": [{"values": [2.0]}]},
            {"metadata": {"name": "a", "unit": "second"}, "runs": [{"values": [4.0], "warmups": [[1, 9.0]]}]},
        ],
    }
    second = {
        "version": "1.0",
        "benchmarks": [
            {"metadata": {"name": "a", "unit": "second"}, "runs": [{"values": [4.0]}]},
            {"metadata": {"name": "b", "unit": "second"}, "runs": [{"values": [2.0]}]},
        ],
    }
    left = compare_suites(first, second, threshold=1.5)
    right = compare_suites(second, first, threshold=1.5)
    assert left["fingerprint"] == right["fingerprint"]
    assert [row["name"] for row in left["rows"]] == ["a", "b"]
    assert left["status"] == "pass"
    assert left["network_calls"] is False
    assert "hostname" not in json.dumps(left)
    assert "must-not-leak" not in json.dumps(left)
    # warmups do not change the sample mean
    with_warmup = compare_suites(first, first, threshold=1.5)
    assert with_warmup["rows"][0]["baseline_mean"] == 4.0


def test_compare_suites_marks_missing_and_unit_conflicts_unavailable() -> None:
    baseline = run_benchmark("kept", (1.0,), unit="second")
    baseline["benchmarks"].append(
        {"metadata": {"name": "dropped", "unit": "second"}, "runs": [{"values": [1.0]}]}
    )
    candidate = run_benchmark("kept", (1.0,), unit="byte")
    candidate["benchmarks"].append(
        {"metadata": {"name": "added", "unit": "second"}, "runs": [{"values": [1.0]}]}
    )
    report = compare_suites(baseline, candidate, threshold=1.5)
    reasons = {row["name"]: row["reason"] for row in report["rows"]}
    assert reasons == {"added": "candidate_only", "dropped": "baseline_only", "kept": "unit_mismatch"}
    assert report["status"] == "unavailable"
    assert all(row["status"] == "unavailable" for row in report["rows"])


def test_compare_suites_rejects_duplicate_names_and_bad_thresholds_without_echoing_samples() -> None:
    suite = run_benchmark("kept", (1.0,))
    suite["benchmarks"].append(suite["benchmarks"][0])
    with pytest.raises(PerfEngineError) as duplicate:
        compare_suites(suite, run_benchmark("kept", (1.0,)))
    assert "duplicate benchmark name" in str(duplicate.value)
    with pytest.raises(PerfEngineError):
        compare_suites(run_benchmark("kept", (1.0,)), run_benchmark("kept", (1.0,)), threshold=1)
    with pytest.raises(PerfEngineError):
        compare_suites(run_benchmark("kept", (1.0,)), run_benchmark("kept", (1.0,)), threshold=True)
    broken = run_benchmark("kept", (1.0,))
    broken["benchmarks"][0]["runs"][0]["values"] = [math.nan]
    with pytest.raises(PerfEngineError) as bad_value:
        compare_suites(broken, broken)
    assert "nan" not in str(bad_value.value).casefold()


def test_incomplete_comparison_fails_closed_even_if_another_row_regresses() -> None:
    baseline = {
        "version": "1.0",
        "benchmarks": [
            {"metadata": {"name": "slow", "unit": "second"}, "runs": [{"values": [2.0]}]},
            {"metadata": {"name": "width", "unit": "second"}, "runs": [{"values": [1.0]}]},
        ],
    }
    candidate = {
        "version": "1.0",
        "benchmarks": [
            {"metadata": {"name": "slow", "unit": "second"}, "runs": [{"values": [6.0]}]},
            {"metadata": {"name": "width", "unit": "byte"}, "runs": [{"values": [1.0]}]},
        ],
    }
    report = compare_suites(baseline, candidate, threshold=2.0)
    assert report["status"] == "unavailable"
    assert {row["name"]: row["status"] for row in report["rows"]} == {"slow": "regression", "width": "unavailable"}
    again = compare_suites(baseline, candidate, threshold=2.0)
    assert report["fingerprint"] == again["fingerprint"]


def test_missing_suites_and_malformed_samples_fail_closed_without_echo() -> None:
    good = run_benchmark("kept", (1.0,))
    with pytest.raises(PerfEngineError, match="baseline suite must be an object"):
        compare_suites(None, good)  # type: ignore[arg-type]
    with pytest.raises(PerfEngineError, match="candidate benchmarks must be a list"):
        compare_suites(good, {"version": "1.0"})
    broken = run_benchmark("kept", (1.0,))
    broken["benchmarks"][0]["runs"][0]["values"] = ["1.0"]
    with pytest.raises(PerfEngineError) as malformed:
        compare_suites(good, broken)
    assert "1.0" not in str(malformed.value)
    named = {"version": "1.0", "benchmarks": [{"metadata": {"name": "kept\nsecret", "unit": "second"}, "runs": [{"values": [1.0]}]}]}
    with pytest.raises(PerfEngineError) as invalid_name:
        compare_suites(named, named)
    assert str(invalid_name.value) == "benchmark name is invalid"
    assert "secret" not in str(invalid_name.value)


def test_empty_suites_are_unavailable_not_a_pass() -> None:
    empty = {"version": "1.0", "benchmarks": []}
    report = compare_suites(empty, empty)
    assert report["status"] == "unavailable"
    assert report["rows"] == []
