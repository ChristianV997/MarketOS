#!/usr/bin/env python3
"""CLI driver for MarketOS deployment, reproducibility failure diagnostics, and promotion rehearsal."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.deployment.diagnostics import run_all_diagnostics
from backend.deployment.promotion_fixtures import SCENARIO_FIXTURES
from backend.deployment.promotion_rehearsal import (
    VALID_PROMOTION_ENVIRONMENTS,
    execute_promotion_rehearsal,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="MarketOS Deployment Diagnostics and Promotion Rehearsal")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    parser.add_argument(
        "--mode",
        choices=["local_dry_run", "staging", "production"],
        default="local_dry_run",
        help="Target validation environment mode for baseline diagnostics",
    )
    parser.add_argument(
        "--promotion-rehearsal",
        action="store_true",
        help="Execute deployment promotion rehearsal and emit operator-ready bundle",
    )
    parser.add_argument(
        "--env",
        "--environment",
        dest="environment",
        choices=sorted(VALID_PROMOTION_ENVIRONMENTS),
        default="local_dry_run",
        help="Target promotion rehearsal environment",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print human-readable summary",
    )
    parser.add_argument(
        "--remediation",
        action="store_true",
        help="Print machine/operator remediation command list",
    )
    parser.add_argument(
        "--hash",
        action="store_true",
        help="Output deterministic replay hash only",
    )
    parser.add_argument(
        "--fixture",
        choices=sorted(SCENARIO_FIXTURES.keys()),
        help="Execute a specific promotion scenario fixture",
    )
    args = parser.parse_args()

    # Promotion rehearsal mode
    if args.promotion_rehearsal or args.fixture:
        if args.fixture:
            fix_fn = SCENARIO_FIXTURES[args.fixture]
            res = fix_fn()
            bundle_dict = res.to_dict() if hasattr(res, "to_dict") else res
            det_hash = getattr(res, "deterministic_hash", "")
            state = getattr(res, "readiness_state", bundle_dict.get("status", "unknown"))
            blockers = getattr(res, "blockers", bundle_dict.get("missing_required_keys", []))
            remediations = getattr(res, "remediations", [])
            env_name = getattr(res, "environment", args.fixture)
        else:
            bundle = execute_promotion_rehearsal(environment=args.environment)
            bundle_dict = bundle.to_dict()
            det_hash = bundle.deterministic_hash
            state = bundle.readiness_state
            blockers = bundle.blockers
            remediations = bundle.remediations
            env_name = bundle.environment

        if args.hash:
            print(det_hash)
            return 0 if state == "passed" else 1

        if args.remediation:
            for r in remediations:
                print(r)
            return 0 if state == "passed" else 1

        if args.json or (not args.summary and not sys.stdout.isatty()):
            print(json.dumps(bundle_dict, indent=2, sort_keys=True))
            return 0 if state == "passed" else 1

        # Human-readable summary
        print("=" * 70)
        print(f"MarketOS Promotion Rehearsal ({env_name})")
        print("=" * 70)
        print(f"Readiness State    : {state.upper()}")
        print(f"Deterministic Hash : {det_hash}")
        print(f"Active Blockers    : {len(blockers)}")
        print(f"Remediations       : {len(remediations)}")
        print("-" * 70)

        if blockers:
            print("BLOCKERS:")
            for b in blockers:
                print(f"  [X] {b}")
            print("-" * 70)

        if remediations:
            print("REMEDIATIONS:")
            for r in remediations:
                print(f"  -> {r}")
            print("-" * 70)

        safe_action = bundle_dict.get("safe_next_action", "")
        if safe_action:
            print(f"Safe Next Action   : {safe_action}")
            print("=" * 70)

        return 0 if state == "passed" else 1

    # Standard diagnostics mode
    report = run_all_diagnostics(mode=args.mode)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Deployment Diagnostics Report (mode: {args.mode})")
        print(f"Status: {report['summary']['status']} ({report['summary']['detected_issues']} issues detected out of {report['summary']['total_checks']} checks)")
        print("-" * 60)
        for item in report["diagnostics"]:
            status_tag = f"[{item['status'].upper()}]"
            print(f"{status_tag:<14} {item['code']}: {item['message']}")
            if item["status"] == "detected":
                print(f"   Remediation: {item['remediation']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
