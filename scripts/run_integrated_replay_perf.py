#!/usr/bin/env python3
"""Canonical replay performance arbitration runner for PR #274.

Does not replace scripts/benchmark_commerce_cycle.py,
scripts/run_commercial_replay_integration.py, or the #280 laboratory.
Does not call providers.
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
    arbitrate,
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


def build_report() -> dict[str, Any]:
    try:
        matrix = arbitrate()
        failure = "ok"
    except IntegratedReplayPerfError as exc:
        matrix = {"schema": "integrated-replay-arbitration-v2", "error": str(exc)}
        failure = "bound_or_timeout"
    missing_infra = [
        "Windows operator checkout",
        "GitHub Actions runner (ci_unavailable)",
        "full-repo quality gate execution",
        "CoderOS probe/health",
    ]
    if matrix.get("canonical", {}).get("status") != "actual":
        missing_infra.append("canonical evaluation.commerce imports in this sandbox")
    return {
        "schema": "integrated-replay-arbitration-v2",
        "repository": "ChristianV997/MarketOS",
        "commit": _git_sha(),
        "command": "python scripts/run_integrated_replay_perf.py --json",
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "windows_operator_packet": "unavailable",
            "coderos": "unavailable",
        },
        "arbitration": matrix,
        "failure_class": failure,
        "ci": "ci_unavailable",
        "missing_infrastructure": missing_infra,
        "rollback": "close draft PR / delete exclusive files; Event and kernel untouched",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.parse_args()
    report = build_report()
    print(json.dumps(report, indent=2, sort_keys=True))
    arb = report.get("arbitration") or {}
    ok = report["failure_class"] == "ok" and arb.get("second_replay_path") is False
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
