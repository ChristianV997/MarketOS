#!/usr/bin/env python3
"""Offline experiment-draft planner. Never publishes or spends."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.commerce.experiment_draft import (  # noqa: E402
    build_experiment_draft,
    client_safe_report,
    reset_registry,
    simulate_experiment_draft,
)
from evaluation.commerce.experiment_draft_scenarios import run_scenarios  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("scenarios", "client-safe"), default="scenarios")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    reset_registry()
    records = run_scenarios()
    if args.mode == "client-safe":
        reset_registry()
        from evaluation.commerce.experiment_draft_scenarios import scenario_payloads

        payload = scenario_payloads()["hydroponics_content_paid_social"]
        draft = build_experiment_draft(payload)
        report = client_safe_report(draft, simulate_experiment_draft(draft))
        print(json.dumps(report, sort_keys=True, indent=2 if args.json else None))
        return 0
    print(json.dumps({"schema": "experiment-draft-scenario-run-v1", "live_action_allowed": False, "records": records}, indent=2 if args.json else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
