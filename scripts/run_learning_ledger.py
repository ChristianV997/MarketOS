#!/usr/bin/env python3
"""Generate the offline Learning Ledger report."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from evaluation.companyos.learning_ledger import EVENT_TYPES, build_learning_ledger_report  # noqa: E402


def _load(path_text: str) -> dict[str, Any]:
    path = Path(path_text).resolve()
    if not path.is_file() or ROOT not in path.parents: raise SystemExit("input path must be an existing file inside the repository")
    try: payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc: raise SystemExit(f"invalid learning input: {exc}") from exc
    rendered = json.dumps(payload).lower()
    if any(marker in rendered for marker in ("api_key", "oauth_token", "private_key", "actual_secret_value", "client@example.com", "real_ad_metric", "begin private key")):
        raise SystemExit("secret-like or client-private learning input rejected")
    if not isinstance(payload, dict): raise SystemExit("learning input must be a JSON object")
    return payload


def _scenario(name: str) -> dict[str, Any]:
    mapping = {
        "ads_winner_loser": {"event_types": ["ad_experiment", "creative_test"]},
        "product_validation_failure": {"event_types": ["product_validation", "supplier_validation"]},
        "frontier_llm_waste": {"event_types": ["model_routing_decision"]},
        "trustos_blocker_recurrence": {"event_types": ["trustos_review", "client_export_review", "provider_run"]},
    }
    if name not in mapping: raise SystemExit(f"unsupported scenario: {name}")
    return mapping[name]


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an offline Learning Ledger.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--event-type", choices=EVENT_TYPES)
    parser.add_argument("--scenario", choices=("ads_winner_loser", "product_validation_failure", "frontier_llm_waste", "trustos_blocker_recurrence"))
    parser.add_argument("--context")
    parser.add_argument("--output")
    args = parser.parse_args()
    context = _load(args.context) if args.context else None
    if args.scenario:
        scenario = _scenario(args.scenario)
        if context:
            context = dict(context); context["scenario"] = args.scenario
        else: context = scenario
        if not args.event_type:
            allowed = set(scenario["event_types"])
            report = build_learning_ledger_report(context=context)
            from dataclasses import replace
            report = replace(report, events=tuple(item for item in report.events if item.event_type in allowed))
        else: report = build_learning_ledger_report(context=context, event_type=args.event_type)
    else: report = build_learning_ledger_report(context=context, event_type=args.event_type)
    if args.output:
        output = Path(args.output).resolve(); output.mkdir(parents=True, exist_ok=True)
        files = {"learning_ledger_report.json": report.to_dict(), "learning_ledger_report.md": report.to_markdown(), "learning_events.json": report.events, "experiments.json": report.experiments, "do_not_repeat_rules.json": report.do_not_repeat_rules, "iteration_recommendations.json": report.iteration_recommendations, "portfolio_impacts.json": report.portfolio_impacts, "model_routing_impacts.json": report.model_routing_impacts, "provider_impacts.json": report.provider_impacts, "trustos_impacts.json": report.trustos_impacts, "decision_influences.json": report.decision_influences}
        for filename, value in files.items():
            if isinstance(value, str): rendered = value
            elif isinstance(value, (tuple, list)): rendered = json.dumps([item.to_dict() if hasattr(item, "to_dict") else item for item in value], indent=2, sort_keys=True)
            else: rendered = json.dumps(value, indent=2, sort_keys=True)
            (output / filename).write_text(rendered + ("\n" if not rendered.endswith("\n") else ""), encoding="utf-8")
        return 0
    print(report.to_markdown() if args.markdown else json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__": raise SystemExit(main())
