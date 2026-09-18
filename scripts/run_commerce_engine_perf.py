#!/usr/bin/env python3
"""Bounded commercial-engine performance and reliability harness.

Measures preprocessing only. Does not call providers, score products,
or replace scripts/benchmark_commerce_cycle.py or
scripts/run_high_value_path_harness.py.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.perf.commerce_engine import (  # noqa: E402
    CommerceEnginePerfError,
    measure_algorithms,
    process_offers,
)


SCENARIOS = (
    "many_candidates",
    "duplicate_ids",
    "correlated_aliases",
    "mixed_evidence",
    "stale_records",
    "conflicting_offers",
    "mixed_currency",
    "missing_costs",
    "nested_variants",
    "malformed",
    "replay",
)


def _git_sha() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=ROOT,
                stderr=subprocess.DEVNULL,
                timeout=3,
            )
            .decode("utf-8")
            .strip()
        )
    except Exception:  # noqa: BLE001 - classification
        return "unavailable"


def _rss_kb() -> int | None:
    try:
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                parts = line.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    return int(parts[1])
    except OSError:
        return None
    return None


def build_rows(scenario: str, size: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index in range(size):
        candidate = f"sku-{index % max(1, size // 4 or 1):04d}"
        row: dict[str, Any] = {
            "candidate_id": candidate,
            "supplier": "fixture-supplier",
            "sku": f"{candidate}-A",
            "currency": "MXN",
            "unit_cost": "180.00",
            "shipping_cost": "45.00",
            "price": "499.00",
            "evidence_state": "fixture",
            "query": "desk organizer",
            "source_family": "manual_csv",
        }
        if scenario == "duplicate_ids":
            row["sku"] = "SHARED"
        elif scenario == "correlated_aliases":
            row["alias_of"] = "sku-0000"
            row["query"] = "desk organizer"
            row["source_family"] = "amazon_search"
        elif scenario == "mixed_evidence":
            row["evidence_state"] = ("fixture", "stale", "observed", "live_readonly")[index % 4]
        elif scenario == "stale_records":
            row["evidence_state"] = "stale"
        elif scenario == "conflicting_offers":
            row["candidate_id"] = "sku-shared"
            row["sku"] = "SHARED"
            row["unit_cost"] = "180.00" if index % 2 == 0 else "220.00"
        elif scenario == "mixed_currency":
            row["currency"] = "MXN" if index % 2 == 0 else "USD"
        elif scenario == "missing_costs":
            row.pop("unit_cost")
            row.pop("shipping_cost")
        elif scenario == "nested_variants":
            row["sku"] = f"{candidate}-{'AB'[index % 2]}"
        elif scenario == "malformed" and index % 7 == 0:
            row = {"html": "<script>"}
        elif scenario == "malformed" and index % 11 == 0:
            row = "not-an-object"
        rows.append(row)
    if scenario == "malformed":
        rows.append({"candidate_id": "secret-row", "api_key": "sk_test_not_real"})
    return rows


def run_scenario(scenario: str, size: int) -> dict[str, Any]:
    rows = build_rows(scenario, size)
    started = time.perf_counter()
    try:
        first = process_offers(rows, job_name=f"perf.{scenario}")
        second = process_offers(rows, job_name=f"perf.{scenario}")
        status = "measured"
        detail = first.failure_class
        replay = first.replay_identity == second.replay_identity
        output_size = len(json.dumps(first.to_dict(), default=str))
        evidence = ",".join(first.evidence_states) or "none"
    except CommerceEnginePerfError as exc:
        status = "bounded_reject"
        detail = str(exc)
        replay = None
        output_size = 0
        evidence = "unavailable"
        first = None
    wall = round((time.perf_counter() - started) * 1000, 3)
    return {
        "scenario": scenario,
        "input_size": len(json.dumps(rows, default=str)),
        "candidate_row_count": len(rows),
        "wall_ms": None if first is None else first.wall_ms,
        "scenario_wall_ms": wall,
        "repeated_run_equality": replay,
        "output_size": output_size,
        "failure_classification": detail,
        "evidence_state": evidence,
        "live_attestation": False if first is None else first.live_attestation,
        "accepted": 0 if first is None else len(first.accepted),
        "rejected": 0 if first is None else len(first.rejected),
        "status": status,
    }


def run_harness(*, size: int, compare: bool) -> dict[str, Any]:
    records = [run_scenario(scenario, size) for scenario in SCENARIOS]
    comparison = measure_algorithms(build_rows("many_candidates", max(size, 1500)), repeats=3) if compare else None
    return {
        "schema": "commerce-engine-perf-report-v1",
        "commit_sha": _git_sha(),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "pid_rss_kb": _rss_kb(),
        },
        "evidence_state": "fixture",
        "size": size,
        "scenarios": records,
        "algorithm_comparison": comparison,
        "authorities_not_replaced": [
            "evaluation.commerce.opportunity_synthesis",
            "backend.economics.kernel",
            "scripts.research_to_decision",
            "scripts.benchmark_commerce_cycle",
            "scripts.run_high_value_path_harness",
        ],
        "live_providers": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, default=int(os.getenv("MARKETOS_COMMERCE_PERF_SIZE", "200")))
    parser.add_argument("--compare-algorithms", action="store_true", default=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = run_harness(size=max(8, min(args.size, 2048)), compare=args.compare_algorithms)
    print(json.dumps(report, sort_keys=True, indent=2 if not args.json else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
