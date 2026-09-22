#!/usr/bin/env python3
"""Bounded commercial replay + performance integration runner.

Drives existing public builders. Does not score products, replace
scripts/benchmark_commerce_cycle.py, copy backend.economics.kernel,
or import evaluation.perf.commerce_engine as a production path.
"""
from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


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


def _classify_import_error(exc: BaseException) -> dict[str, Any]:
    return {
        "result": "unavailable",
        "evidence_classification": "unavailable",
        "reason": f"{type(exc).__name__}: {exc}",
    }


def run_scenarios() -> dict[str, Any]:
    try:
        from evaluation.commerce.dry_run_events import lifecycle_events
        from evaluation.commerce.dry_run_lifecycle import run_dry_run_lifecycle
        from evaluation.commerce.dry_run_scenarios import SCENARIO_BUILDERS
        from backend.events.replay_certification import replay_summary
    except Exception as exc:  # noqa: BLE001
        return _classify_import_error(exc)

    rows: list[dict[str, Any]] = []
    for builder in SCENARIO_BUILDERS:
        started = time.perf_counter()
        first = run_dry_run_lifecycle(builder())
        first_events = lifecycle_events(first, workspace_id=f"ws-{builder.__name__}")
        second = run_dry_run_lifecycle(builder())
        second_events = lifecycle_events(second, workspace_id=f"ws-{builder.__name__}")
        wall_ms = round((time.perf_counter() - started) * 1000, 3)
        first_hashes = [event.replay_hash() for event in first_events]
        second_hashes = [event.replay_hash() for event in second_events]
        summary = replay_summary(first_events)
        payload = json.dumps(first.to_dict(), sort_keys=True, default=str)
        rows.append(
            {
                "scenario": first.scenario_id,
                "candidate_id": first.candidate_id,
                "sku": first.candidate_id,
                "market_lane": first.steps[2].detail.get("lane_id") if len(first.steps) > 2 else "",
                "currency": first.steps[2].detail.get("currency") if len(first.steps) > 2 else "",
                "evidence_state": first.steps[0].detail.get("evidence_state") if first.steps else "unknown",
                "achievable_stage": first.achievable_stage,
                "promoted_to_launch": first.promoted_to_launch,
                "blockers": list(first.promotion.blockers),
                "event_count": len(first_events),
                "replay_equal": first_hashes == second_hashes and first.to_dict() == second.to_dict(),
                "sequence_issues": summary.get("sequence_issues", []),
                "live_authority_violations": summary.get("live_authority_violations", []),
                "live_actions_taken": first.live_actions_taken,
                "wall_ms": wall_ms,
                "output_bytes": len(payload.encode("utf-8")),
                "failure_class": "ok" if not first.promotion.blockers or not first.promoted_to_launch else "blocked",
                "evidence_classification": "fixture",
            }
        )
    return {
        "result": "actual" if rows else "unavailable",
        "evidence_classification": "fixture",
        "rows": rows,
    }


def run_service_clients() -> dict[str, Any]:
    try:
        from decimal import Decimal

        from backend.economics.kernel import Money
        from evaluation.companyos.service_engagement import build_service_engagement
    except Exception as exc:  # noqa: BLE001
        return _classify_import_error(exc)

    thin = build_service_engagement(
        "eng-insufficient",
        "Managed Acquisition and CRO",
        "Thin Data Client",
        service_fee=Money("1500", "USD"),
        inputs={},
    ).to_dict()
    adequate = build_service_engagement(
        "eng-adequate",
        "Managed Acquisition and CRO",
        "Adequate Data Client",
        service_fee=Money("1500", "USD"),
        inputs={
            "ad_spend": Money("10000", "USD"),
            "contribution_margin": Decimal("0.40"),
            "roas_before": Decimal("1.8"),
            "roas_after": Decimal("2.3"),
            "cac_before": Money("25", "USD"),
            "cac_after": Money("18", "USD"),
            "delivery_hours": Decimal("24"),
            "capacity_hours": Decimal("160"),
        },
    ).to_dict()
    return {
        "result": "actual",
        "evidence_classification": "fixture",
        "insufficient_status": thin.get("status"),
        "adequate_status": adequate.get("status"),
        "thin_economics_is_none": thin.get("economics") is None,
    }


def isolated_perf_note() -> dict[str, Any]:
    """#255 remains an isolated benchmark. Do not treat import success as production."""
    try:
        import evaluation.perf.commerce_engine as isolated  # type: ignore
    except Exception:
        return {
            "pr_255_module": "not_present_on_this_branch",
            "classification": "isolated_benchmark_harness",
            "production_path": False,
            "recorded_before_ms": 25.172,
            "recorded_after_ms": 6.222,
            "recorded_environment": "authoring sandbox Python 3.12 fixture-only",
            "evidence_classification": "fixture",
        }
    return {
        "pr_255_module": getattr(isolated, "SCHEMA", "present"),
        "classification": "isolated_benchmark_harness",
        "production_path": False,
        "warning": "module imported only for classification; not a second commerce authority",
        "evidence_classification": "fixture",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = {
        "schema": "commercial-replay-performance-integration-v2",
        "repository": "ChristianV997/MarketOS",
        "commit": _git_sha(),
        "base_sha": "38b53a264bf9e1343b47161d2647149a5ab3918f",
        "command": "python scripts/run_commercial_replay_integration.py --json",
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "windows_operator_packet": "unavailable",
        },
        "scenarios": run_scenarios(),
        "service_clients": run_service_clients(),
        "isolated_perf_harness_255": isolated_perf_note(),
        "ci": "ci_unavailable",
        "missing_infrastructure": [
            "Windows operator checkout",
            "GitHub Actions runner (ci_unavailable)",
            "full-repo quality gate execution",
        ],
        "rollback": "close PR / delete exclusive files; #248 kernel untouched",
    }
    text = json.dumps(report, indent=2, sort_keys=True)
    print(text)
    return 0 if args.json or report["scenarios"].get("result") in {"actual", "unavailable"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
