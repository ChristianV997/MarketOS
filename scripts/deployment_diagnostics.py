#!/usr/bin/env python3
"""CLI driver for MarketOS deployment and reproducibility failure diagnostics."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.deployment.diagnostics import run_all_diagnostics


def main() -> int:
    parser = argparse.ArgumentParser(description="MarketOS Deployment Diagnostics")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    parser.add_argument(
        "--mode",
        choices=["local_dry_run", "staging", "production"],
        default="local_dry_run",
        help="Target validation environment mode",
    )
    args = parser.parse_args()

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
