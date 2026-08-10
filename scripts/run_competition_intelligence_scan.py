"""Gather public competitor-listing evidence and build a Market
Intelligence / Margin Intelligence report, deterministically.

Advisory, read-only, no provider mutation: this never places an order,
creates a listing, or authenticates to any competitor site. Public pages
only, no credentials, same safety posture as
scripts/run_commerce_mvp_slice.py's supplier-evidence path.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.contracts.adapters import SidecarContext
from backend.events.repository import JsonlEventRepository
from backend.mvp_commerce.competition_intelligence import (
    build_market_opportunity_report, compute_margin_intelligence, competition_intelligence_events, gather_market_intelligence,
)
from backend.mvp_commerce.supplier_evidence import SupplierEvidenceResult


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gather public competitor-listing evidence and compute market/margin intelligence.")
    parser.add_argument("--query", required=True)
    parser.add_argument("--competitor-urls", help="comma-separated public listing URLs")
    parser.add_argument("--competitor-urls-fixture", help="JSON file containing a list of competitor URLs (fixture/dry-run mode)")
    parser.add_argument("--allow-network", action="store_true", help="perform real fetches; without this, evidence is dry-run/simulated")
    parser.add_argument("--max-competitors", type=int, default=10)
    parser.add_argument("--supplier-unit-cost", type=float, default=None, help="observed supplier unit cost, for margin computation")
    parser.add_argument("--supplier-shipping-cost", type=float, default=None)
    parser.add_argument("--candidate-id", default="cli-candidate")
    parser.add_argument("--product-name", default="")
    parser.add_argument("--workspace-id", default="competition-intelligence-cli")
    parser.add_argument("--run-id", default="competition-intelligence-cli-run")
    parser.add_argument("--write-jsonl")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--markdown", action="store_true")
    return parser


def _competitor_urls(args: argparse.Namespace, parser: argparse.ArgumentParser) -> list[str]:
    if args.competitor_urls and args.competitor_urls_fixture:
        parser.error("--competitor-urls cannot be combined with --competitor-urls-fixture")
    if args.competitor_urls_fixture:
        value = json.loads((ROOT / args.competitor_urls_fixture).read_text(encoding="utf-8"))
        urls = value.get("competitor_urls", value) if isinstance(value, dict) else value
        return [str(url) for url in urls]
    if args.competitor_urls:
        return [url.strip() for url in args.competitor_urls.split(",") if url.strip()]
    return []


def _write_markdown(report: dict[str, Any]) -> None:
    print("# Competition Intelligence scan")
    print()
    print(f"- Query: `{report['query']}`")
    print(f"- Observed competitors: {report['observed_competitor_count']}")
    print(f"- Median price: {report['observed_median_price']}")
    print(f"- Market saturation: {report['market_saturation']}")
    print(f"- Market maturity: `{report['market_maturity']}`")
    print(f"- Confidence: {report['confidence']}")
    print()
    print("Advisory only; no order, listing, or credential action was executed.")
    for warning in report.get("warnings", []):
        print(f"- Warning: {warning}")
    margin = report.get("margin")
    if margin:
        print()
        print("## Margin intelligence")
        print(f"- Observed gross margin: {margin['observed_gross_margin']}")
        print(f"- Observed supplier advantage: {margin['observed_supplier_advantage']}")
        for warning in margin.get("warnings", []):
            print(f"- Warning: {warning}")


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.markdown and args.as_json:
        parser.error("choose --json or --markdown, not both")

    urls = _competitor_urls(args, parser)
    context = SidecarContext(workspace_id=args.workspace_id, dry_run=not args.allow_network)
    market_report = gather_market_intelligence(args.query, context=context, competitor_urls=urls, max_competitors=args.max_competitors)

    supplier_evidence = None
    if args.supplier_unit_cost is not None:
        supplier_evidence = SupplierEvidenceResult(
            attempted=True, unit_cost=args.supplier_unit_cost, shipping_cost=args.supplier_shipping_cost, source_url="operator-supplied",
        )
    margin = compute_margin_intelligence(args.candidate_id, supplier_evidence=supplier_evidence, market_report=market_report)
    opportunity_report = build_market_opportunity_report(
        args.candidate_id, args.product_name or args.query, supplier_evidence=supplier_evidence,
        market_report=market_report, margin=margin,
    )
    events = competition_intelligence_events(market_report, margin, opportunity_report, workspace_id=args.workspace_id, run_id=args.run_id)

    report = market_report.to_dict()
    report["margin"] = margin.to_dict()
    report["market_opportunity_report"] = opportunity_report.to_dict()
    report["event_count"] = len(events)
    report["event_type_counts"] = dict(sorted({event.event_type: sum(item.event_type == event.event_type for item in events) for event in events}.items()))
    report["read_only"] = True
    report["advisory"] = True
    report["mutated"] = False
    report["network_used"] = args.allow_network

    if args.write_jsonl:
        JsonlEventRepository(ROOT / args.write_jsonl).append_many(events)
        report["write_targets"] = ["jsonl"]
    else:
        report["write_targets"] = []

    if args.markdown:
        _write_markdown(report)
    else:
        print(json.dumps(report, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
