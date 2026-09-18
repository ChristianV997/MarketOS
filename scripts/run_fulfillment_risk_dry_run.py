"""Emit one bounded supplier-direct fulfillment risk dry-run report."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.commerce.fulfillment_risk_lifecycle import (
    SCENARIO_NAMES,
    build_named_adapter,
    build_named_scenario,
    run_fulfillment_risk_dry_run,
)


def _markdown(report: dict[str, object]) -> str:
    return "\n".join(
        (
            "# Fulfillment Risk Dry Run",
            f"- Scenario: `{report['scenario_id']}`",
            f"- State: `{report['current_state']}`",
            f"- Status: `{report['status']}`",
            f"- Evidence: `{report['evidence_state']}`",
            f"- Blockers: {', '.join(report['blockers']) or 'none'}",
            f"- SLA risks: {', '.join(report['sla_risks']) or 'none'}",
            f"- Next human action: `{report['next_human_action']}`",
            "- Live action allowed: `false`",
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=SCENARIO_NAMES, default="successful_direct_shipment")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)
    if args.as_json and args.markdown:
        parser.error("choose --json or --markdown")
    report = run_fulfillment_risk_dry_run(
        build_named_scenario(args.scenario), adapter=build_named_adapter(args.scenario)
    )
    payload = report.to_dict()
    if args.markdown:
        print(_markdown(payload))
    else:
        print(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
