"""Generate the offline Product Opportunity Synthesis v1."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.adapters.research.consumer_attention import import_json as import_attention_json  # noqa: E402
from backend.adapters.research.marketplace_trends import import_json as import_marketplace_json  # noqa: E402
from backend.adapters.research.supplier_feasibility import import_json as import_supplier_json  # noqa: E402
from evaluation.commerce.consumer_attention import build_report as build_attention_report  # noqa: E402
from evaluation.commerce.marketplace_trends import build_report as build_marketplace_report  # noqa: E402
from evaluation.commerce.opportunity_synthesis import build_product_opportunity_synthesis  # noqa: E402
from evaluation.commerce.supplier_feasibility import build_report as build_supplier_report  # noqa: E402

DEFAULT_MARKETPLACE = ROOT / "tests" / "fixtures" / "marketplace_trends" / "amazon_best_sellers_snapshot.json"
DEFAULT_SUPPLIER = ROOT / "tests" / "fixtures" / "supplier_feasibility" / "cj_validation_pack_success.json"
DEFAULT_CONSUMER = ROOT / "tests" / "fixtures" / "consumer_attention" / "tiktok_creative_center_snapshot.json"


def _read(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    target = Path(path)
    # Normalize both separator styles so Windows-form paths are rejected when
    # the CLI is exercised on Linux CI (and vice versa).
    path_parts = path.replace("\\", "/").split("/")
    if ".." in target.parts or ".." in path_parts or target.suffix.lower() != ".json":
        raise ValueError("only local JSON report paths without traversal are supported")
    if not target.is_file():
        raise ValueError(f"synthesis input does not exist: {target}")
    value = json.loads(target.read_text(encoding="utf8"))
    if not isinstance(value, dict):
        raise ValueError(f"synthesis input must be a JSON object: {target}")
    return value


def _default_reports() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    marketplace = build_marketplace_report(import_marketplace_json(DEFAULT_MARKETPLACE, marketplace="amazon"), evidence_mode="fixture_demo").to_dict()
    reference_prices = {
        item.get("candidate_id"): item.get("evidence", [{}])[0].get("price")
        for item in marketplace.get("candidates", [])
        if item.get("evidence") and item.get("evidence", [{}])[0].get("price") is not None
    }
    supplier = build_supplier_report(import_supplier_json(DEFAULT_SUPPLIER, supplier="cj", source_type="cj_validation_pack_report"), evidence_mode="fixture_demo", target_sell_prices=reference_prices).to_dict()
    consumer = build_attention_report(import_attention_json(DEFAULT_CONSUMER, platform="tiktok", source_type="tiktok_creative_center_snapshot"), evidence_mode="fixture_demo").to_dict()
    return marketplace, supplier, consumer


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Product Opportunity Synthesis",
        "",
        f"Evidence mode: `{report['evidence_mode']}` (offline; not launch authorization)",
        f"Top candidate: **{report.get('top_candidate_title') or 'none'}** (`{report.get('top_candidate_id') or 'none'}`)",
        f"Overall recommendation: `{report['overall_recommendation']}`",
        f"Combined opportunity: {float(report.get('combined_opportunity_score', 0) or 0):.0%}",
        f"Confidence: {float(report.get('evidence_confidence', 0) or 0):.0%} / `{report.get('confidence_grade')}`",
        "",
        "## Executive Decision",
        "",
        report.get("client_summary", ""),
        "",
        "## Opportunity Scorecard",
        "",
        "| Candidate | Combined | Marketplace | Supplier | Attention | Grade | Recommendation |",
        "| --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for candidate in report.get("candidates", []):
        score = candidate["score"]
        recommendation = score["recommendation"]["code"]
        lines.append(f"| {candidate['title']} | {score['combined_opportunity_score']:.0%} | {score['marketplace_opportunity']:.0%} | {score['supplier_feasibility']:.0%} | {score['consumer_attention']:.0%} | `{score['confidence_grade']}` | `{recommendation}` |")
    lines += [
        "",
        "## Evidence Confidence Matrix",
        "",
        str(report.get("risk_profile", {})),
        "",
        "## Decision Thresholds",
        "",
        str(report.get("decision_thresholds", {})),
        "",
        "## 14-Day Validation Plan",
        "",
    ]
    lines.extend(f"- **Day {item.get('window', '')}:** {item.get('task', '')}" for item in report.get("fourteen_day_validation_plan", []))
    lines += [
        "",
        "## Operator Decision",
        "",
        report.get("operator_summary", ""),
        "",
        "This report is validation guidance. Fixture/manual evidence cannot authorize launch, ad spend, publishing, orders, or provider mutations.",
        "",
    ]
    return "\n".join(lines)


def _write_output(directory: str, report: dict[str, Any], markdown_text: str) -> None:
    target = Path(directory)
    if ".." in target.parts:
        raise ValueError("output traversal is not allowed")
    target.mkdir(parents=True, exist_ok=True)
    (target / "opportunity_synthesis_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf8")
    (target / "opportunity_synthesis_report.md").write_text(markdown_text, encoding="utf8")
    checklist = [
        "Confirm the evidence mode and source provenance.",
        "Review supplier cost, shipping, inventory, and delivery gaps.",
        "Review the recommended price band and break-even assumptions.",
        "Approve or reject the next bounded validation step.",
    ]
    (target / "client_action_checklist.md").write_text("# Client Action Checklist\n\n" + "\n".join(f"- [ ] {item}" for item in checklist) + "\n", encoding="utf8")
    (target / "operator_decision_summary.json").write_text(json.dumps({"top_candidate_id": report.get("top_candidate_id"), "recommendation": report.get("overall_recommendation"), "next_best_action": report.get("next_best_action"), "read_only": True, "network_calls": False, "mutated": False}, indent=2, sort_keys=True) + "\n", encoding="utf8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline Product Opportunity Synthesis v1")
    parser.add_argument("--marketplace-trend-report")
    parser.add_argument("--supplier-feasibility-report")
    parser.add_argument("--consumer-attention-report")
    parser.add_argument("--product-validation-report")
    parser.add_argument("--client-context")
    parser.add_argument("--output")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)
    if args.json and args.markdown:
        parser.error("choose --json or --markdown")
    try:
        if any((args.marketplace_trend_report, args.supplier_feasibility_report, args.consumer_attention_report)):
            market = _read(args.marketplace_trend_report)
            supplier = _read(args.supplier_feasibility_report)
            consumer = _read(args.consumer_attention_report)
        else:
            market, supplier, consumer = _default_reports()
        report = build_product_opportunity_synthesis(market, supplier, consumer, product_validation_report=_read(args.product_validation_report), client_context=_read(args.client_context)).to_dict()
        output = markdown(report)
        if args.output:
            _write_output(args.output, report, output)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(output if args.markdown else json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
