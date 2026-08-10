"""Build a Product Research portfolio (identity resolution, clustering,
bucketed ranking) from fixture or public-network signals, deterministically.

Advisory, read-only, no provider mutation. Supports optionally gathering
real supplier/competitor evidence per candidate (bounded, same safety gates
as scripts/run_commerce_mvp_slice.py and
scripts/run_competition_intelligence_scan.py).
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
from backend.mvp_commerce.competition_intelligence import compute_margin_intelligence, gather_market_intelligence
from backend.mvp_commerce.opportunity import build_opportunity_candidates_from_signals
from backend.mvp_commerce.opportunity_scoring import score_opportunity
from backend.mvp_commerce.product_research import (
    PortfolioBucketEntry, ResearchCandidate, ResearchPortfolio, ResearchQuality,
    build_research_portfolio, compare_portfolios, product_research_events,
)
from backend.mvp_commerce.runner import _load_signals
from backend.mvp_commerce.supplier_evidence import gather_supplier_evidence
from backend.signals.public_sources import ingest_public_rss


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a Product Research portfolio from fixture or public signals.")
    parser.add_argument("--fixture")
    parser.add_argument("--public-query")
    parser.add_argument("--allow-public-network", action="store_true")
    parser.add_argument("--max-signals", type=int, default=10)
    parser.add_argument("--max-candidates", type=int, default=5)
    parser.add_argument("--gather-evidence", action="store_true", help="attempt real supplier + competitor evidence per candidate (bounded by --max-candidates)")
    parser.add_argument("--allow-network", action="store_true", help="perform real evidence fetches; without this, evidence gathering is dry-run/simulated")
    parser.add_argument("--workspace-id", default="product-research-cli")
    parser.add_argument("--run-id", default="product-research-cli-run")
    parser.add_argument("--previous-portfolio-json", help="a prior run's --json output file, to compute ranking movement against")
    parser.add_argument("--write-jsonl")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--clusters", action="store_true", help="markdown output focuses on the cluster report instead of the portfolio summary")
    return parser


def _entry_from_dict(value: dict[str, Any]) -> PortfolioBucketEntry:
    return PortfolioBucketEntry(value["candidate_id"], value["product_name"], value["composite_score"], value["confidence"], tuple(value["reasons"]))


def _load_previous_portfolio(path: str) -> ResearchPortfolio:
    """Reconstructs a ResearchPortfolio from a prior run's --json output
    (portfolio.to_dict()) — a real, lossless round-trip (every field
    compare_portfolios() needs is present), not a reconstruction from the
    lossy, decoded read-API summary (which only carries bucket counts, not
    full bucket contents — see docs/PRODUCT_RESEARCH.md)."""
    value = json.loads((ROOT / path).read_text(encoding="utf-8"))
    quality = ResearchQuality(**value["quality"])
    buckets = {
        name: tuple(_entry_from_dict(entry) for entry in value[name])
        for name in ("top_opportunities", "emerging_opportunities", "undervalued_opportunities",
                      "high_risk_opportunities", "high_uncertainty_opportunities", "rejected_candidates")
    }
    return ResearchPortfolio(
        value["workspace_id"], value["query"], value["generated_at"], tuple(value["candidate_ids"]),
        (), (), quality, buckets["top_opportunities"], buckets["emerging_opportunities"], buckets["undervalued_opportunities"],
        buckets["high_risk_opportunities"], buckets["high_uncertainty_opportunities"], buckets["rejected_candidates"],
        value["top_candidate_id"],
    )


def _write_markdown(portfolio, show_clusters: bool) -> None:
    if show_clusters:
        print("# Product Research clusters")
        print()
        for cluster in portfolio.clusters:
            print(f"## {cluster.name}")
            print(f"- Members: {len(cluster.member_ids)}")
            print(f"- Confidence: {cluster.confidence}")
            print(f"- Price range: {cluster.price_range}")
            print(f"- Supplier diversity: {cluster.supplier_diversity}; competition diversity: {cluster.competition_diversity}")
            print()
        return
    print("# Product Research portfolio")
    print()
    print(f"- Query: `{portfolio.query}`")
    print(f"- Candidates: {len(portfolio.candidate_ids)}")
    print(f"- Clusters: {len(portfolio.clusters)}")
    print(f"- Top candidate: `{portfolio.top_candidate_id or 'none'}`")
    print()
    print("Advisory only; no order, listing, launch, or spend action was executed.")
    for label, bucket in (
        ("Top opportunities", portfolio.top_opportunities), ("Emerging opportunities", portfolio.emerging_opportunities),
        ("Undervalued opportunities", portfolio.undervalued_opportunities), ("High-risk opportunities", portfolio.high_risk_opportunities),
        ("High-uncertainty opportunities", portfolio.high_uncertainty_opportunities), ("Rejected candidates", portfolio.rejected_candidates),
    ):
        if bucket:
            print()
            print(f"## {label} ({len(bucket)})")
            for entry in bucket:
                print(f"- `{entry.candidate_id}` — {entry.product_name}: score={entry.composite_score}, confidence={entry.confidence}")


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.markdown and args.as_json:
        parser.error("choose --json or --markdown, not both")
    if not args.fixture and not args.public_query:
        parser.error("--fixture or --public-query is required")

    if args.public_query:
        ingestion = ingest_public_rss(args.public_query, limit=args.max_signals, allow_network=args.allow_public_network)
        rows = ingestion.signals
        query = args.public_query
    else:
        rows = _load_signals(ROOT / args.fixture)[:args.max_signals]
        query = rows[0].query if rows else ""

    candidates = build_opportunity_candidates_from_signals(rows, args.workspace_id, query, args.max_candidates)
    context = SidecarContext(workspace_id=args.workspace_id, dry_run=not args.allow_network)

    research_candidates = []
    for candidate in candidates:
        supplier_evidence = None
        competition_evidence = None
        if args.gather_evidence:
            supplier_evidence = gather_supplier_evidence(candidate.product_name, context=context)
            competition_evidence = gather_market_intelligence(candidate.product_name, context=context)
        margin = compute_margin_intelligence(candidate.candidate_id, supplier_evidence=supplier_evidence, market_report=competition_evidence) if args.gather_evidence else None
        score = score_opportunity(candidate, supplier_evidence=supplier_evidence, competition_evidence=competition_evidence, margin=margin)
        research_candidates.append(ResearchCandidate(candidate.candidate_id, candidate, score, supplier_evidence, competition_evidence))

    portfolio = build_research_portfolio(research_candidates, workspace_id=args.workspace_id, query=query)
    comparison = None
    if args.previous_portfolio_json:
        previous = _load_previous_portfolio(args.previous_portfolio_json)
        comparison = compare_portfolios(previous, portfolio)

    events = product_research_events(portfolio, research_candidates, run_id=args.run_id, comparison=comparison)

    report = portfolio.to_dict()
    if comparison is not None:
        report["comparison"] = comparison.to_dict()
    report["event_count"] = len(events)
    report["event_type_counts"] = dict(sorted({event.event_type: sum(item.event_type == event.event_type for item in events) for event in events}.items()))
    report["read_only"] = True
    report["advisory"] = True
    report["mutated"] = False
    report["network_used"] = args.allow_network and args.gather_evidence

    if args.write_jsonl:
        JsonlEventRepository(ROOT / args.write_jsonl).append_many(events)
        report["write_targets"] = ["jsonl"]
    else:
        report["write_targets"] = []

    if args.markdown:
        _write_markdown(portfolio, args.clusters)
    else:
        print(json.dumps(report, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
