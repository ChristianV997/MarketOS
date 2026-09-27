"""Copy-pattern of the pyperf 2.8.1 BenchmarkSuite JSON contract.

Upstream: https://github.com/psf/pyperf
Pinned revision (authoritative tag 2.8.1): c58426688e1a28b2519695a3869b98dc51f3a69d
License at pin: MIT (COPYING — Copyright 2016, Red Hat, Inc. and Google Inc.)
Inspected at pin: pyperf/_bench.py, pyperf/_runner.py, COPYING

This module does not import, vendor, or depend on pyperf. It reproduces the
JSON 1.0 suite shape documented in pyperf/_bench.py at the pin:

    version, suite metadata, benchmarks[].runs[].values, optional warmups

Host/CPU metadata collection from pyperf (`collect_metadata`, hostname,
python_executable, aslr, platform, cpu_model_name) is intentionally omitted
so the encoder stays offline and deterministic. Values are operator-supplied
samples; this module never times a live workload, opens a socket, or reads
credentials.

Registry note: data/source_adaptation_registry.json currently pins
c0e9eb8a78fd148f0746ba2b9cb030206dfd8478 for src-pyperf. That SHA is not a
commit on psf/pyperf. This module uses the verified tag object instead and
does not rewrite the frozen 29-record registry (stable-hash contract).

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
        "hostname",
        "python_executable",
        "aslr",
        "platform",
        "cpu_model_name",
        "cpu_affinity",
        "cpu_count",
        "cpu_frequency",
    }
)


class PerfEngineError(ValueError):
    """Raised when a copied pyperf suite cannot be represented safely."""


def _finite_positive(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise PerfEngineError(f"{name} must be numeric") from exc
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
        name = str(key)
        lower = name.lower()
        if lower in _FORBIDDEN_METADATA_KEYS:
            raise PerfEngineError(f"host metadata {name} is not collected")
        if any(
            marker in lower
            for marker in ("token", "secret", "password", "api_key", "credential")
        ):
            raise PerfEngineError(f"sensitive metadata key {name}")
        if isinstance(value, float) and not math.isfinite(value):
            raise PerfEngineError(f"metadata {name} must be finite")
        cleaned[name] = value
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
    label = " ".join(str(name).split())
    if not label:
        raise PerfEngineError("benchmark name is required")
    samples = tuple(
        _finite_positive(item, f"values[{index}]") for index, item in enumerate(values)
    )
    if not samples:
        raise PerfEngineError("values must be a non-empty sequence")
    warmup_rows: list[list[float | int]] = []
    for index, item in enumerate(warmups or ()):
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            raise PerfEngineError(f"warmups[{index}] must be (loops, value)")
        loops, warmup_value = item
        if not isinstance(loops, int) or loops < 1:
            raise PerfEngineError(f"warmups[{index}] loops must be an int >= 1")
        measured = float(warmup_value)
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
        "read_only": True,
        "mutated": False,
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
    "dump_suite",
    "run_benchmark",
]
