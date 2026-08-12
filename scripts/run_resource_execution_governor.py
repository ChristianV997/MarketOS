#!/usr/bin/env python3
"""Run the offline Resource & Execution Governor report."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.companyos.resource_execution_governor import (  # noqa: E402
    ACTION_TYPES,
    ExecutionDecisionRequest,
    build_resource_execution_governor_report,
    request_from_mapping,
)


def _load_json(path_text: str) -> dict[str, Any]:
    path = Path(path_text).resolve()
    if not path.is_file() or ROOT not in path.parents:
        raise SystemExit("input path must be an existing file inside the repository")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"invalid governor input: {exc}") from exc
    rendered = json.dumps(payload).lower()
    if any(marker in rendered for marker in ("actual_secret_value", "api_key", "password", "sk-", "begin private key", "oauth_token")):
        raise SystemExit("secret-like governor input rejected")
    if not isinstance(payload, dict):
        raise SystemExit("governor input must be a JSON object")
    if "action_type" in payload and not isinstance(payload["action_type"], str):
        raise SystemExit("malformed governor input rejected")
    if "requested_amount" in payload and not isinstance(payload["requested_amount"], (int, float)):
        raise SystemExit("malformed governor input rejected")
    return payload


def _filter_report(report, action: str | None):
    if not action:
        return report
    if action not in ACTION_TYPES:
        raise SystemExit(f"unsupported action: {action}")
    decisions = tuple(item for item in report.decisions if item.action_type == action)
    if not decisions:
        raise SystemExit(f"no decision generated for action: {action}")
    from dataclasses import replace
    return replace(report, decisions=decisions)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an offline Resource & Execution Governor report.")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument("--markdown", action="store_true", help="emit Markdown")
    parser.add_argument("--action", choices=ACTION_TYPES)
    parser.add_argument("--scenario", choices=("product_to_launch_pipeline", "ads_kill_scale_loop", "model_cost_control"))
    parser.add_argument("--context")
    parser.add_argument("--output")
    args = parser.parse_args()
    context = _load_json(args.context) if args.context else {}
    requests = None
    if isinstance(context.get("requests"), list):
        requests = tuple(request_from_mapping(item) for item in context["requests"] if isinstance(item, dict))
    report = build_resource_execution_governor_report(context=context, requests=requests)
    if args.scenario:
        scenario_map = {
            "product_to_launch_pipeline": {"screen_product_opportunities", "deep_validate_product", "promote_product_candidate", "generate_launch_draft", "generate_site_draft"},
            "ads_kill_scale_loop": {"launch_ad_experiment", "kill_ad_experiment", "scale_ad_budget", "generate_creative_batch"},
            "model_cost_control": {"run_local_llm_task", "run_cheap_llm_task", "run_frontier_llm_synthesis"},
        }
        from dataclasses import replace
        report = replace(report, decisions=tuple(item for item in report.decisions if item.action_type in scenario_map[args.scenario]))
    report = _filter_report(report, args.action)
    if args.output:
        output = Path(args.output).resolve()
        output.mkdir(parents=True, exist_ok=True)
        (output / "resource_execution_governor_report.json").write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (output / "resource_execution_governor_report.md").write_text(report.to_markdown(), encoding="utf-8")
        for name, value in {"decision_results.json": report.decisions, "budget_checks.json": tuple(check for item in report.decisions for check in item.budget_checks), "quota_checks.json": tuple(check for item in report.decisions for check in item.quota_checks), "model_spend_policy.json": report.model_policy, "provider_spend_policy.json": report.provider_policy, "portfolio_policy.json": report.portfolio_policy, "experiment_policy.json": report.experiment_policy, "runaway_guard_policy.json": report.runaway_policy, "learning_capture_requirements.json": report.learning_requirements, "cross_department_dependencies.json": report.dependencies}.items():
            (output / name).write_text(json.dumps(value.to_dict() if hasattr(value, "to_dict") else [item.to_dict() for item in value], indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0
    if args.markdown:
        print(report.to_markdown())
    else:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
