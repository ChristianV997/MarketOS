"""Copy-pattern of the pyperf 2.8.1 BenchmarkSuite JSON contract.

Upstream: https://github.com/psf/pyperf
Pinned revision (authoritative tag 2.8.1): c58426688e1a28b2519695a3869b98dc51f3a69d
License at pin: MIT (COPYING — Copyright 2016, Red Hat, Inc. and Google Inc.)
Inspected at pin: pyperf/_bench.py, pyperf/_metadata.py, pyperf/_formatter.py, COPYING

This module does not import, vendor, or depend on pyperf. It reproduces the
JSON 1.0 suite shape documented in pyperf/_bench.py at the pin:

    version, suite metadata, benchmarks[].runs[].values, optional warmups

Host/CPU metadata collection from pyperf (`collect_metadata`, hostname,
python_executable, aslr, platform, cpu_model_name) is intentionally omitted
so the encoder stays offline and deterministic. Values are operator-supplied
samples; this module never times a live workload, opens a socket, or reads
credentials. Recognized host/secret/runtime metadata keys are rejected, but
arbitrary caller-supplied free-text values are not content-scanned.

Registry note: data/source_adaptation_registry.json currently records
c0e9eb8a78fd148f0746ba2b9cb030206dfd8478 for src-pyperf, which differs from
the verified 2.8.1 release commit. This module uses the verified release
commit and does not rewrite the frozen 29-record registry (stable-hash contract).

Rollback: delete this file and the matching contract test / notice row.
Existing replay/lab benchmarks do not import this module.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping, Sequence

UPSTREAM_REPOSITORY = "https://github.com/psf/pyperf"
UPSTREAM_COMMIT_SHA = "c58426688e1a28b2519695a3869b98dc51f3a69d"
UPSTREAM_TAG = "2.8.1"
UPSTREAM_LICENSE = "MIT"
UPSTREAM_LICENSE_EVIDENCE = (
    "https://github.com/psf/pyperf/blob/c58426688e1a28b2519695a3869b98dc51f3a69d/COPYING"
)
JSON_VERSION = "1.0"
SOURCE_ID = "src-pyperf"
# Stale registry pin retained only as a documented defect; not used at runtime.
REGISTRY_RECORDED_SHA = "c0e9eb8a78fd148f0746ba2b9cb030206dfd8478"

_FORBIDDEN_METADATA_KEYS = frozenset(
    {
        "architecture",
        "cpu",
        "cpuaffinity",
        "cpucount",
        "cpufrequency",
        "cpumodelname",
        "cwd",
        "host",
        "hostname",
        "ip",
        "ipaddress",
        "kernel",
        "macaddress",
        "machine",
        "machinename",
        "networkcalls",
        "networkinterface",
        "os",
        "platform",
        "pythonexecutable",
        "pythonimplementation",
        "pythonversion",
        "aslr",
        "system",
        "user",
        "username",
        "workingdirectory",
        "collecthostmetadata",
        "device",
        "environment",
        "environmentvariables",
        "hardware",
        "runtime",
        "runtimeversion",
    }
)
_FORBIDDEN_METADATA_MARKERS = (
    "architecture",
    "cpu",
    "host",
    "ipaddress",
    "kernel",
    "machine",
    "macaddress",
    "network",
    "platform",
    "processor",
    "pythonexecutable",
    "pythonimplementation",
    "pythonversion",
    "system",
    "workingdirectory",
)
_SENSITIVE_METADATA_MARKERS = (
    "accesskey",
    "apikey",
    "auth",
    "bearer",
    "cookie",
    "credential",
    "password",
    "privatekey",
    "secret",
    "sessionid",
    "token",
)
_RESERVED_METADATA_KEYS = frozenset({"name", "unit"})
_UNSUPPORTED_RUNTIME_METADATA_KEYS = frozenset(
    {
        "boottime",
        "calibrateloops",
        "calibratewarmups",
        "commandmaxrss",
        "date",
        "duration",
        "innerloops",
        "loadavg1min",
        "loops",
        "memmaxrss",
        "mempeakpagefileusage",
        "recalibrateloops",
        "recalibratewarmups",
        "uptime",
    }
)
_SUPPORTED_UNITS = frozenset({"byte", "integer", "second"})


class PerfEngineError(ValueError):
    """Raised when a copied pyperf suite cannot be represented safely."""


def _finite_positive(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PerfEngineError(f"{name} must be a finite number > 0")
    try:
        number = float(value)
    except OverflowError as exc:
        raise PerfEngineError(f"{name} must be finite") from exc
    if not math.isfinite(number) or number <= 0.0:
        raise PerfEngineError(f"{name} must be a finite number > 0")
    return number


def _clean_metadata(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    if metadata is None:
        return {}
    if not isinstance(metadata, Mapping):
        raise PerfEngineError("metadata must be an object")
    cleaned: dict[str, Any] = {}
    for key, value in metadata.items():
        if not isinstance(key, str) or not key.strip():
            raise PerfEngineError("metadata keys must be non-empty strings")
        name = key.strip()
        normalized = "".join(character for character in name.casefold() if character.isalnum())
        if normalized in _RESERVED_METADATA_KEYS:
            raise PerfEngineError(f"metadata field {name} is reserved")
        if normalized in _UNSUPPORTED_RUNTIME_METADATA_KEYS:
            raise PerfEngineError(f"runtime metadata {name} is not supplied offline")
        if normalized in _FORBIDDEN_METADATA_KEYS or any(
            marker in normalized for marker in _FORBIDDEN_METADATA_MARKERS
        ):
            raise PerfEngineError(f"host metadata {name} is not collected")
        if any(marker in normalized for marker in _SENSITIVE_METADATA_MARKERS):
            raise PerfEngineError(f"sensitive metadata key {name}")
        if normalized == "tags":
            if name != "tags":
                raise PerfEngineError("tags metadata key must be lowercase")
            if not isinstance(value, (list, tuple)) or not value:
                raise PerfEngineError("tags must be a non-empty list of strings")
            tags = [tag.strip() if isinstance(tag, str) else "" for tag in value]
            if any(
                not tag
                or tag.casefold() == "all"
                or "\n" in tag
                or chr(13) in tag
                for tag in tags
            ):
                raise PerfEngineError("tags must be non-empty strings other than 'all'")
            cleaned[name] = tags
        elif isinstance(value, str):
            text = value.strip()
            if not text or "\n" in value or chr(13) in value:
                raise PerfEngineError(f"metadata {name} must be a non-empty single-line string")
            cleaned[name] = text
        elif isinstance(value, float):
            if not math.isfinite(value):
                raise PerfEngineError(f"metadata {name} must be finite")
            cleaned[name] = value
        elif isinstance(value, (int, bool)):
            cleaned[name] = value
        else:
            raise PerfEngineError(f"metadata {name} must be a JSON scalar or tags list")
    return cleaned


def run_benchmark(
    name: str,
    values: Sequence[Any],
    *,
    unit: str = "second",
    warmups: Sequence[tuple[int, float]] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one offline pyperf-shaped suite from operator-supplied samples.

    ``values`` are loop-normalized samples, matching pyperf JSON 1.0.
    Warmups are ``(loops, value)`` pairs. No process, network, or host probe runs.
    """
    if not isinstance(name, str):
        raise PerfEngineError("benchmark name must be a string")
    label = " ".join(name.split())
    if not label:
        raise PerfEngineError("benchmark name is required")
    if not isinstance(unit, str) or unit not in _SUPPORTED_UNITS:
        raise PerfEngineError(f"unit must be one of {', '.join(sorted(_SUPPORTED_UNITS))}")
    if isinstance(values, (str, bytes, bytearray)):
        raise PerfEngineError("values must be a non-empty sequence of numbers")
    try:
        samples = tuple(
            _finite_positive(item, f"values[{index}]")
            for index, item in enumerate(values)
        )
    except TypeError as exc:
        raise PerfEngineError("values must be a non-empty sequence") from exc
    if not samples:
        raise PerfEngineError("values must be a non-empty sequence")
    warmup_rows: list[list[float | int]] = []
    try:
        warmup_items = tuple(warmups) if warmups is not None else ()
    except TypeError as exc:
        raise PerfEngineError("warmups must be a sequence") from exc
    for index, item in enumerate(warmup_items):
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            raise PerfEngineError(f"warmups[{index}] must be (loops, value)")
        loops, warmup_value = item
        if isinstance(loops, bool) or not isinstance(loops, int) or loops < 1:
            raise PerfEngineError(f"warmups[{index}] loops must be an int >= 1")
        if isinstance(warmup_value, bool) or not isinstance(warmup_value, (int, float)):
            raise PerfEngineError(f"warmups[{index}] value must be numeric")
        try:
            measured = float(warmup_value)
        except OverflowError as exc:
            raise PerfEngineError(f"warmups[{index}] value must be finite") from exc
        if not math.isfinite(measured) or measured < 0.0:
            raise PerfEngineError(f"warmups[{index}] value must be finite and >= 0")
        warmup_rows.append([loops, measured])
    suite_metadata = {
        "source_id": SOURCE_ID,
        "upstream_repository": UPSTREAM_REPOSITORY,
        "upstream_commit_sha": UPSTREAM_COMMIT_SHA,
        "upstream_tag": UPSTREAM_TAG,
        "license": UPSTREAM_LICENSE,
        "network_calls": False,
        "collect_host_metadata": False,
    }
    run: dict[str, Any] = {"values": list(samples)}
    if warmup_rows:
        run["warmups"] = warmup_rows
    bench_metadata = {"name": label, "unit": unit, **_clean_metadata(metadata)}
    suite = {
        "version": JSON_VERSION,
        "metadata": suite_metadata,
        "benchmarks": [{"metadata": bench_metadata, "runs": [run]}],
    }
    try:
        encoded = json.dumps(
            suite, sort_keys=True, allow_nan=False, separators=(",", ":")
        )
    except (TypeError, ValueError) as exc:
        raise PerfEngineError("suite must be finite JSON") from exc
    suite["suite_fingerprint"] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return suite


def dump_suite(suite: Mapping[str, Any]) -> str:
    payload = dict(suite)
    payload.pop("suite_fingerprint", None)
    return json.dumps(payload, sort_keys=True, allow_nan=False, indent=2)


def _mean(samples: Sequence[float]) -> float:
    return sum(samples) / len(samples)


def _benchmark_rows(suite: Mapping[str, Any], label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(suite, Mapping):
        raise PerfEngineError(f"{label} suite must be an object")
    if suite.get("version") != JSON_VERSION:
        raise PerfEngineError(f"{label} suite version must be 1.0")
    benchmarks = suite.get("benchmarks")
    if not isinstance(benchmarks, list):
        raise PerfEngineError(f"{label} benchmarks must be a list")
    rows: dict[str, dict[str, Any]] = {}
    for bench in benchmarks:
        if not isinstance(bench, Mapping):
            raise PerfEngineError("benchmark must be an object")
        metadata = bench.get("metadata")
        if not isinstance(metadata, Mapping):
            raise PerfEngineError("benchmark metadata must be an object")
        name = metadata.get("name")
        unit = metadata.get("unit")
        if not isinstance(name, str) or not name.strip():
            raise PerfEngineError("benchmark name is required")
        if name in rows:
            raise PerfEngineError("duplicate benchmark name")
        if unit not in _SUPPORTED_UNITS:
            raise PerfEngineError("benchmark unit is not supported")
        runs = bench.get("runs")
        if not isinstance(runs, list) or not runs:
            raise PerfEngineError("benchmark runs must be a non-empty list")
        samples: list[float] = []
        for run in runs:
            if not isinstance(run, Mapping):
                raise PerfEngineError("benchmark run must be an object")
            values = run.get("values")
            if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence) or not values:
                raise PerfEngineError("benchmark values must be a non-empty sequence")
            samples.extend(_finite_positive(item, "value") for item in values)
        rows[name] = {"unit": unit, "mean": _mean(samples)}
    return rows


def compare_suites(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    threshold: float = 1.05,
) -> dict[str, Any]:
    """Compare two supplied suites. Smaller means are better. No timing or host probe runs.

    A candidate mean strictly above ``threshold`` times the baseline is a regression.
    A mean strictly below the baseline divided by ``threshold`` is an improvement.
    Names or units that do not match are unavailable, not a pass. Warmups are ignored.
    """
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise PerfEngineError("threshold must be a finite number > 1")
    limit = float(threshold)
    if not math.isfinite(limit) or limit <= 1.0:
        raise PerfEngineError("threshold must be a finite number > 1")
    base_rows = _benchmark_rows(baseline, "baseline")
    candidate_rows = _benchmark_rows(candidate, "candidate")
    names = sorted(set(base_rows) | set(candidate_rows))
    compared: list[dict[str, Any]] = []
    for name in names:
        left = base_rows.get(name)
        right = candidate_rows.get(name)
        if left is None or right is None or left["unit"] != right["unit"]:
            reason = "unit_mismatch" if left is not None and right is not None else (
                "baseline_only" if right is None else "candidate_only"
            )
            compared.append({"name": name, "status": "unavailable", "reason": reason})
            continue
        ratio = right["mean"] / left["mean"]
        if ratio > limit:
            status = "regression"
        elif ratio < (1.0 / limit):
            status = "improvement"
        else:
            status = "pass"
        compared.append(
            {
                "name": name,
                "unit": left["unit"],
                "baseline_mean": left["mean"],
                "candidate_mean": right["mean"],
                "ratio": ratio,
                "status": status,
            }
        )
    statuses = {row["status"] for row in compared}
    if not compared:
        overall = "unavailable"
    elif "regression" in statuses:
        overall = "regression"
    elif "unavailable" in statuses:
        overall = "unavailable"
    elif "improvement" in statuses:
        overall = "improvement"
    else:
        overall = "pass"
    body = {
        "schema": "pyperf-suite-compare-v1",
        "threshold": limit,
        "network_calls": False,
        "collect_host_metadata": False,
        "status": overall,
        "rows": compared,
    }
    encoded = json.dumps(body, sort_keys=True, allow_nan=False, separators=(",", ":"))
    body["fingerprint"] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return body


__all__ = [
    "JSON_VERSION",
    "PerfEngineError",
    "REGISTRY_RECORDED_SHA",
    "SOURCE_ID",
    "UPSTREAM_COMMIT_SHA",
    "UPSTREAM_LICENSE",
    "UPSTREAM_LICENSE_EVIDENCE",
    "UPSTREAM_REPOSITORY",
    "UPSTREAM_TAG",
    "compare_suites",
    "dump_suite",
    "run_benchmark",
]
