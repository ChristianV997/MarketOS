"""Contract tests for the src-pyperf JSON 1.0 copy-pattern.

No pyperf dependency. Samples are fixtures. Network and host probes stay off.
"""
from __future__ import annotations

import ast
import json
import math
import random
from fractions import Fraction
from pathlib import Path

import pytest

from scripts.benchmarks.perf_engine import (
    JSON_VERSION,
    MAX_BENCHMARKS,
    MAX_NAME_LENGTH,
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


# --- Property-style and adversarial coverage (seeded stdlib RNG, synthetic samples only) ---


def _raw_suite(rows: list[tuple[str, str, list[float]]]) -> dict:
    return {
        "version": "1.0",
        "benchmarks": [
            {"metadata": {"name": name, "unit": unit}, "runs": [{"values": list(values)}]} for name, unit, values in rows
        ],
    }


def _one(base: float, candidate: float, *, threshold: float = 1.05) -> dict:
    return compare_suites(
        _raw_suite([("b", "second", [base])]), _raw_suite([("b", "second", [candidate])]), threshold=threshold
    )


def test_sample_order_and_run_partition_never_change_the_mean_or_classification() -> None:
    rng = random.Random(344)
    for _ in range(300):
        samples = [rng.choice([0.1, 0.2, 0.3, 1e-9, 1e9, 3.3, 7.7]) * rng.randint(1, 50) for _ in range(rng.randint(2, 12))]
        shuffled = samples[:]
        rng.shuffle(shuffled)
        cut = rng.randint(1, len(shuffled) - 1)
        base = _raw_suite([("b", "second", samples)])
        split = {
            "version": "1.0",
            "benchmarks": [{"metadata": {"name": "b", "unit": "second"}, "runs": [{"values": shuffled[:cut]}, {"values": shuffled[cut:]}]}],
        }
        report = compare_suites(base, split, threshold=1.0000001)
        row = report["rows"][0]
        assert row["baseline_mean"] == row["candidate_mean"]
        assert row["ratio"] == 1.0 and report["status"] == "pass"
        assert compare_suites(split, base, threshold=1.0000001)["fingerprint"] == report["fingerprint"]


def test_swapping_baseline_and_candidate_swaps_regression_and_improvement_exactly() -> None:
    rng = random.Random(3440)
    for _ in range(4000):
        base = rng.uniform(0.5, 5.0)
        limit = rng.choice([1.05, 1.2, 1.5, 2.0])
        candidate = base * rng.choice([1.0, limit, 1 / limit, 1.0499999999, 1.0500000001, 0.95, 1.2, 0.8])
        forward = _one(base, candidate, threshold=limit)["status"]
        backward = _one(candidate, base, threshold=limit)["status"]
        assert (forward, backward) in {("pass", "pass"), ("regression", "improvement"), ("improvement", "regression")}


@pytest.mark.parametrize("limit", [1.05, 1.25, 1.5, 2.0, 3.0])
def test_candidate_equal_to_threshold_times_baseline_is_a_pass_and_one_ulp_beyond_is_not(limit: float) -> None:
    base = 4.0
    exactly = float(Fraction(limit) * Fraction(base))
    assert Fraction(exactly) == Fraction(limit) * Fraction(base)  # exactly representable
    assert _one(base, exactly, threshold=limit)["status"] == "pass"
    assert _one(base, math.nextafter(exactly, math.inf), threshold=limit)["status"] == "regression"
    # mirror: candidate * limit == baseline is a pass, one ulp below is an improvement
    assert _one(exactly, base, threshold=limit)["status"] == "pass"
    assert _one(exactly, math.nextafter(base, 0.0), threshold=limit)["status"] == "improvement"


def test_sample_sum_overflow_uses_the_exact_mean_instead_of_failing() -> None:
    huge = 1.7e308  # two of these overflow a float sum; their mean does not
    report = compare_suites(_raw_suite([("b", "second", [huge, huge])]), _raw_suite([("b", "second", [huge])]))
    assert report["status"] == "pass"
    assert report["rows"][0]["baseline_mean"] == huge
    assert math.isfinite(report["rows"][0]["ratio"])


def test_out_of_range_ratio_and_threshold_raise_a_safe_error() -> None:
    with pytest.raises(PerfEngineError, match="ratio is out of range"):
        _one(5e-324, 1e300)
    good = _raw_suite([("b", "second", [1.0])])
    for threshold in (10**1000, -(10**1000)):
        with pytest.raises(PerfEngineError, match="threshold"):
            compare_suites(good, good, threshold=threshold)
    # the opposite extreme is representable and a clear improvement
    assert _one(1e300, 5e-324)["status"] == "improvement"


@pytest.mark.parametrize("unit", [["second"], {"u": 1}, 1, None, ("second",)], ids=["list", "dict", "int", "none", "tuple"])
def test_non_string_units_are_a_safe_error_not_a_type_error(unit: object) -> None:
    broken = {"version": "1.0", "benchmarks": [{"metadata": {"name": "b", "unit": unit}, "runs": [{"values": [1.0]}]}]}
    with pytest.raises(PerfEngineError, match="unit is not supported"):
        compare_suites(broken, _raw_suite([("b", "second", [1.0])]))


_BAD_NAMES = {
    "line-separator": "a\u2028b",
    "paragraph-separator": "a\u2029b",
    "bidi-override": "a\u202eb",
    "zero-width-space": "a\u200bb",
    "soft-hyphen": "a\u00adb",
    "nul": "a\x00b",
    "lone-surrogate": "a\ud800b",
}


_WHITESPACE_SEPARATORS = {"line-separator", "paragraph-separator"}  # the encoder folds these into a single space


@pytest.mark.parametrize("name", list(_BAD_NAMES.values()), ids=list(_BAD_NAMES))
def test_control_and_format_characters_in_names_are_rejected_by_the_comparator(name: str) -> None:
    suite = _raw_suite([(name, "second", [1.0])])
    with pytest.raises(PerfEngineError) as compared:
        compare_suites(suite, suite)
    assert str(compared.value) == "benchmark name is invalid"  # exact message: the name is never echoed


@pytest.mark.parametrize(
    "name", [value for key, value in _BAD_NAMES.items() if key not in _WHITESPACE_SEPARATORS],
    ids=[key for key in _BAD_NAMES if key not in _WHITESPACE_SEPARATORS],
)
def test_encoder_rejects_the_names_its_own_comparator_rejects(name: str) -> None:
    with pytest.raises(PerfEngineError) as built:
        run_benchmark(name, (1.0,))
    assert str(built.value) == "benchmark name is invalid"


@pytest.mark.parametrize("name", [_BAD_NAMES["line-separator"], _BAD_NAMES["paragraph-separator"]], ids=["U+2028", "U+2029"])
def test_encoder_folds_line_separators_into_a_space_that_compares(name: str) -> None:
    suite = run_benchmark(name, (1.0,))
    assert suite["benchmarks"][0]["metadata"]["name"] == "a b"
    assert compare_suites(suite, suite)["rows"][0]["name"] == "a b"


def test_name_length_is_bounded_and_the_encoder_output_always_compares() -> None:
    longest = "n" * MAX_NAME_LENGTH
    suite = run_benchmark(longest, (1.0,))
    assert compare_suites(suite, suite)["status"] == "pass"
    for build in (
        lambda: run_benchmark(longest + "n", (1.0,)),
        lambda: compare_suites(_raw_suite([(longest + "n", "second", [1.0])]), suite),
    ):
        with pytest.raises(PerfEngineError, match="benchmark name is too long"):
            build()
    for name in ("plain", "with space", "unicode-é-名前", "dots.and-dashes_ok"):
        built = run_benchmark(name, (1.0,))
        assert compare_suites(built, built)["rows"][0]["name"] == " ".join(name.split())


def test_benchmark_count_is_bounded_and_the_report_stays_small() -> None:
    def many(prefix: str, count: int) -> dict:
        return _raw_suite([((f"{prefix}{index}_").ljust(MAX_NAME_LENGTH, "x"), "second", [1.5, 2.5]) for index in range(count)])

    left, right = many("a", MAX_BENCHMARKS), many("b", MAX_BENCHMARKS)
    report = compare_suites(left, right)
    assert report["status"] == "unavailable" and len(report["rows"]) == 2 * MAX_BENCHMARKS
    assert len(json.dumps(report)) < 2 * MAX_BENCHMARKS * (MAX_NAME_LENGTH + 320)
    for oversize, side in ((many("a", MAX_BENCHMARKS + 1), "baseline"), (many("b", MAX_BENCHMARKS + 1), "candidate")):
        args = (oversize, right) if side == "baseline" else (left, oversize)
        with pytest.raises(PerfEngineError, match=f"{side} suite has too many benchmarks"):
            compare_suites(*args)


def test_hostile_structures_only_ever_raise_the_safe_error() -> None:
    rng = random.Random(34400)
    junk = [None, True, False, 0, -1, 1.5, math.nan, math.inf, -math.inf, 10**400, "", "x", "second", [], {}, [[]], {"a": 1}, (1, 2), b"1", object()]
    template = {
        "version": "1.0",
        "metadata": {"hostname": "must-not-leak"},
        "benchmarks": [
            {"metadata": {"name": "a", "unit": "second"}, "runs": [{"values": [1.0, 2.0], "warmups": [[1, 0.5]]}]},
            {"metadata": {"name": "b", "unit": "byte"}, "runs": [{"values": [3.0]}]},
        ],
    }

    def mutate(node: object, depth: int = 0) -> object:
        if isinstance(node, dict):
            node = dict(node)
            for key in list(node):
                if rng.random() < 0.18:
                    node[key] = rng.choice(junk) if rng.random() < 0.7 else mutate(node[key], depth + 1)
                elif rng.random() < 0.05:
                    del node[key]
                else:
                    node[key] = mutate(node[key], depth + 1)
            return node
        if isinstance(node, list):
            node = [mutate(item, depth + 1) for item in node]
            if node and rng.random() < 0.1:
                node[rng.randrange(len(node))] = rng.choice(junk)
            return node
        return node

    clean = compare_suites(template, template)
    assert clean["status"] == "pass"
    accepted = rejected = 0
    for _ in range(3000):
        left, right = mutate(template), mutate(template)
        try:
            report = compare_suites(left, right, threshold=rng.choice([1.05, 2, 1e308, 1.0000001]))
        except PerfEngineError as error:
            rejected += 1
            assert "must-not-leak" not in str(error)
            continue
        accepted += 1
        assert report["status"] in {"pass", "regression", "improvement", "unavailable"}
        assert "must-not-leak" not in json.dumps(report)
        assert len(json.dumps(report)) < 400_000
    assert accepted and rejected


def test_hostile_encoder_arguments_only_ever_raise_the_safe_error() -> None:
    rng = random.Random(344000)
    junk = [None, True, 0, -1, 1.5, math.nan, math.inf, 10**400, "", "x", [], {}, [[]], (1, 2), b"1", object(), "a\x00b", "n" * 500]
    for _ in range(1500):
        args = [rng.choice(junk) for _ in range(3)]
        try:
            run_benchmark(args[0], args[1], unit=args[2], warmups=rng.choice([None, args[1], ((1, 2.0),)]), metadata=rng.choice([None, args[2], {"k": args[0]}]))
        except PerfEngineError:
            pass


def test_incomparable_unit_and_name_mismatches_never_rank_and_report_stable_reasons() -> None:
    left = _raw_suite([("only-left", "second", [1.0]), ("both", "second", [1.0]), ("both-unit", "second", [1.0])])
    right = _raw_suite([("only-right", "second", [1.0]), ("both", "second", [9.0]), ("both-unit", "byte", [1.0])])
    report = compare_suites(left, right, threshold=1.5)
    rows = {row["name"]: row for row in report["rows"]}
    assert report["status"] == "unavailable"
    assert rows["both"]["status"] == "regression"
    assert {key: rows[key]["reason"] for key in ("only-left", "only-right", "both-unit")} == {
        "only-left": "baseline_only", "only-right": "candidate_only", "both-unit": "unit_mismatch",
    }
    assert all("ratio" not in rows[key] for key in ("only-left", "only-right", "both-unit"))
