#!/usr/bin/env python3
"""Bounded integrated commercial-replay performance runner.

Does not replace scripts/benchmark_commerce_cycle.py or
scripts/run_commercial_replay_integration.py. Does not call providers.
"""
from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.perf.integrated_replay import (  # noqa: E402
    IntegratedReplayPerfError,
    MAX_CANDIDATES,
    SIZES,
    classify_canonical,
    measure_matrix,
    sanitized_candidates,
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
    except Exception:  # noqa: BLE001
        return "unavailable"


def build_report(sizes: tuple[int, ...]) -> dict[str, Any]:
    try:
        matrix = measure_matrix(sizes)
        failure = "ok"
    except IntegratedReplayPerfError as exc:
        matrix = {
            "schema": "integrated-replay-perf-v1",
            "sizes": [],
            "error": str(exc),
            "canonical": classify_canonical(),
        }
        failure = "bound_or_timeout"
    return {
        "schema": "integrated-replay-perf-v1",
        "repository": "ChristianV997/MarketOS",
        "commit": _git_sha(),
        "command": "python scripts/run_integrated_replay_perf.py --json",
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "windows_operator_packet": "unavailable",
        },
        "matrix": matrix,
        "failure_class": failure,
        "ci": "ci_unavailable",
        "missing_infrastructure": [
            "Windows operator checkout",
            "GitHub Actions runner (ci_unavailable)",
            "full-repo quality gate execution",
            "canonical evaluation.commerce imports in this sandbox",
        ],
        "rollback": "close draft PR / delete exclusive files; Event and kernel untouched",
        "sources": [
            "pytest-benchmark wall-time + equality concept",
            "OpenLineage run identity concept",
            "stdlib hashlib / json / time only",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--size", type=int, default=0, help="single size; 0 runs the default matrix")
    args = parser.parse_args()
    if args.size:
        if args.size > MAX_CANDIDATES:
            print(json.dumps({"error": "candidate bound exceeded", "max": MAX_CANDIDATES}))
            return 1
        sanitized_candidates(args.size)
        report = build_report((args.size,))
    else:
        report = build_report(SIZES)
    text = json.dumps(report, indent=2, sort_keys=True)
    print(text)
    matrix = report.get("matrix") or {}
    ok = matrix.get("all_replay_stable", False) and matrix.get("no_live_upgrade", False)
    return 0 if report["failure_class"] == "ok" and (ok or args.json) else 1


if __name__ == "__main__":
    raise SystemExit(main())
