"""Rank a deterministic, gate-aware MarketOS engineering backlog."""
from __future__ import annotations

import argparse
import json
from typing import Any

try:
    from .operating_layer import render_json_or_markdown, write_optional_output
except ImportError:  # pragma: no cover - direct script execution
    from operating_layer import render_json_or_markdown, write_optional_output


DEFAULT_BACKLOG = [
    {"task": "finish_cj_live_validation_pack", "commercial": 4, "evidence": 5, "risk_reduction": 5, "unblocking": 5, "ci": 2, "operator": 5, "effort": 2, "scope_risk": 1, "safety_risk": 1, "gate": "active_pr_review"},
    {"task": "run_cj_credentialed_readonly_validation", "commercial": 5, "evidence": 5, "risk_reduction": 5, "unblocking": 5, "ci": 1, "operator": 5, "effort": 2, "scope_risk": 2, "safety_risk": 2, "gate": "credentials_and_operator_approval"},
    {"task": "optimize_ci_test_lanes", "commercial": 2, "evidence": 3, "risk_reduction": 4, "unblocking": 4, "ci": 5, "operator": 2, "effort": 3, "scope_risk": 2, "safety_risk": 1, "gate": "safe_now"},
    {"task": "expand_evidence_benchmark_matrix", "commercial": 3, "evidence": 5, "risk_reduction": 3, "unblocking": 3, "ci": 2, "operator": 3, "effort": 3, "scope_risk": 3, "safety_risk": 2, "gate": "cj_live_result"},
    {"task": "deploy_readonly_validation_stack", "commercial": 3, "evidence": 3, "risk_reduction": 4, "unblocking": 3, "ci": 2, "operator": 5, "effort": 4, "scope_risk": 3, "safety_risk": 2, "gate": "phase1_readiness_report"},
    {"task": "operator_cockpit_readiness_summary", "commercial": 2, "evidence": 2, "risk_reduction": 2, "unblocking": 2, "ci": 1, "operator": 4, "effort": 3, "scope_risk": 2, "safety_risk": 1, "gate": "read_only_stack_deployed"},
    {"task": "design_mutation_approval_ledger", "commercial": 4, "evidence": 2, "risk_reduction": 5, "unblocking": 4, "ci": 2, "operator": 4, "effort": 5, "scope_risk": 4, "safety_risk": 5, "gate": "phase1_live_readiness"},
]


def score(item: dict[str, Any]) -> float:
    benefit = 3 * item["commercial"] + 4 * item["evidence"] + 3 * item["risk_reduction"] + 3 * item["unblocking"] + 2 * item["ci"] + 2 * item["operator"]
    cost = 2 * item["effort"] + 3 * item["scope_risk"] + 4 * item["safety_risk"]
    return round((benefit - cost) / 10, 2)


def plan(items: list[dict[str, Any]]) -> dict[str, Any]:
    ranked = [{**item, "impact_score": score(item)} for item in items]
    ranked.sort(key=lambda item: (-item["impact_score"], item["task"]))
    return {"planner": "marketos-impact-v1", "task_count": len(ranked), "ranked_backlog": ranked, "principle": "execute one unblocked, high-impact task at a time"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", help="optional JSON list of scored task objects")
    parser.add_argument("--json", action="store_true"); parser.add_argument("--markdown", action="store_true"); parser.add_argument("--output")
    args = parser.parse_args(argv)
    if args.json and args.markdown: parser.error("choose --json or --markdown")
    items = json.loads(open(args.input, encoding="utf-8").read()) if args.input else DEFAULT_BACKLOG
    report = plan(items)
    content = render_json_or_markdown(report, markdown=args.markdown, title="MarketOS impact backlog")
    write_optional_output(content, args.output); print(content, end="")
    return 0


if __name__ == "__main__": raise SystemExit(main())
