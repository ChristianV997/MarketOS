#!/usr/bin/env python3
"""Benchmark deterministic inference routing and the canonical commerce loop."""
from __future__ import annotations

import argparse
import json
import math
import os
import time
import tracemalloc
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _percentile(samples: list[float], percentile: float) -> float:
    ordered = sorted(samples)
    index = min(len(ordered) - 1, math.ceil(len(ordered) * percentile) - 1)
    return ordered[index]


def _summary(samples: list[float]) -> dict[str, float]:
    return {
        "min_ms": round(min(samples), 3),
        "median_ms": round(_percentile(samples, 0.50), 3),
        "p95_ms": round(_percentile(samples, 0.95), 3),
        "max_ms": round(max(samples), 3),
    }


def benchmark(runs: int = 50) -> dict[str, object]:
    if runs < 1:
        raise ValueError("runs must be at least 1")
    previous_chain = os.environ.get("INFERENCE_PROVIDERS")
    os.environ["INFERENCE_PROVIDERS"] = "mock"
    from backend.inference.models.inference_request import InferenceRequest
    from backend.inference.policies.routing_policy import RoutingPolicy
    from backend.inference.providers.mock import MockProvider
    from backend.inference.router import InferenceRouter

    provider = MockProvider()
    policy = RoutingPolicy()
    routing_samples: list[float] = []
    completion_samples: list[float] = []
    router = InferenceRouter(providers=[provider], provider_failure_backoff_s=0)
    try:
        for index in range(runs):
            request = InferenceRequest(prompt="benchmark", sequence_id=f"routing-{index}", max_tokens=16, seed=7)
            started = time.perf_counter()
            policy.select(request, [provider])
            routing_samples.append((time.perf_counter() - started) * 1000)
            started = time.perf_counter()
            response = router.complete(request)
            if not response.content:
                raise RuntimeError("mock completion returned empty content")
            completion_samples.append((time.perf_counter() - started) * 1000)
        tracemalloc.start()
        for index in range(runs):
            router.complete(InferenceRequest(prompt="memory", sequence_id=f"memory-{index}", max_tokens=8, seed=7))
        _, peak_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        return {
            "runs": runs,
            "provider": "mock",
            "routing": _summary(routing_samples),
            "completion": _summary(completion_samples),
            "peak_memory_bytes": peak_bytes,
            "cache_size": router.cache_size(),
        }
    finally:
        if previous_chain is None:
            os.environ.pop("INFERENCE_PROVIDERS", None)
        else:
            os.environ["INFERENCE_PROVIDERS"] = previous_chain


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=50)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        report = benchmark(args.runs)
    except (RuntimeError, ValueError) as exc:
        print(f"inference benchmark failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2 if args.json else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
