#!/usr/bin/env python3
"""Measure the canonical commerce loop's deterministic dry-run latency.

This intentionally uses explicit attributed inputs and no external providers,
so a p95 regression represents MarketOS execution work rather than network
variance. It is suitable for CI and local release checks.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _inputs() -> tuple[list[dict], dict[str, dict], dict[str, dict]]:
    quality = {"provenance": "live", "attribution": "attributed", "source_ref": "benchmark"}
    return (
        [{
            "id": "benchmark-signal", "product_id": "benchmark-product", "product": "Benchmark Product",
            "source": "benchmark", "platform": "test", "score": 0.9, "engagement": 0.8, "velocity": 0.7,
            "quality": quality,
        }],
        {"benchmark-product": {"product_id": "benchmark-product", "name": "Benchmark Product", "selling_price": 60.0, "quality": quality}},
        {"benchmark-product": {"supplier_id": "benchmark-supplier", "product_id": "benchmark-product", "unit_cost": 15.0, "shipping_cost": 5.0, "inventory_units": 100, "quality": quality}},
    )


def benchmark(runs: int = 20, *, p95_limit_ms: float = 2000.0) -> dict[str, float | int | bool]:
    if runs < 1:
        raise ValueError("runs must be at least 1")
    # The normal runtime may prefer a locally configured provider. For this
    # benchmark, force the deterministic mock chain before the commerce stack
    # is imported so no loopback model request becomes part of the measurement.
    previous_chain = os.environ.get("INFERENCE_PROVIDERS")
    os.environ["INFERENCE_PROVIDERS"] = "mock"
    from backend.inference import router as inference_router
    from backend.commerce import run_commerce_cycle

    previous_router = inference_router._router
    inference_router._router = None
    try:
        signals, products, offers = _inputs()
        # Warm imports, vector fallbacks, and deterministic static state before
        # measuring the steady-state commerce path.
        report = run_commerce_cycle(signals=signals, products=products, offers=offers, top_k=1, budget=10.0, dry_run=True)
        if not report.dry_run or report.summary.get("feedback_records") != 1:
            raise RuntimeError("commerce dry-run benchmark did not complete the canonical feedback path")
        samples: list[float] = []
        for _ in range(runs):
            started = time.perf_counter()
            report = run_commerce_cycle(signals=signals, products=products, offers=offers, top_k=1, budget=10.0, dry_run=True)
            if not report.dry_run or report.summary.get("feedback_records") != 1:
                raise RuntimeError("commerce dry-run benchmark did not complete the canonical feedback path")
            samples.append((time.perf_counter() - started) * 1000)
        ordered = sorted(samples)
        p95 = ordered[min(len(ordered) - 1, math.ceil(len(ordered) * 0.95) - 1)]
        return {
            "runs": runs,
            "min_ms": round(ordered[0], 3),
            "median_ms": round(ordered[len(ordered) // 2], 3),
            "p95_ms": round(p95, 3),
            "p95_limit_ms": p95_limit_ms,
            "within_limit": p95 <= p95_limit_ms,
        }
    finally:
        inference_router._router = previous_router
        if previous_chain is None:
            os.environ.pop("INFERENCE_PROVIDERS", None)
        else:
            os.environ["INFERENCE_PROVIDERS"] = previous_chain


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--p95-limit-ms", type=float, default=float(os.getenv("MARKETOS_COMMERCE_CYCLE_P95_LIMIT_MS", "2000")))
    args = parser.parse_args()
    try:
        result = benchmark(args.runs, p95_limit_ms=args.p95_limit_ms)
    except (ValueError, RuntimeError) as exc:
        print(f"commerce benchmark failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0 if result["within_limit"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
