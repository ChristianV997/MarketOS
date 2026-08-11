"""Run the offline marketplace trend intelligence vertical slice."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.adapters.research.marketplace_trends import (  # noqa: E402
    MarketplaceImportError,
    import_csv,
    import_json,
)
from evaluation.commerce.marketplace_trends import (  # noqa: E402
    MarketplaceTrendEvidence,
    build_report,
    collapse_duplicates,
)

DEFAULT = ROOT / "tests" / "fixtures" / "marketplace_trends" / "amazon_best_sellers_snapshot.json"


def _load_records(args: argparse.Namespace) -> list[MarketplaceTrendEvidence]:
    if args.manual_import:
        return import_csv(args.manual_import, marketplace=args.marketplace)
    if args.candidate_seed:
        return import_json(args.candidate_seed, marketplace=args.marketplace or "amazon")
    return import_json(DEFAULT, marketplace=args.marketplace or "amazon")


def _bounded_records(records: Iterable[MarketplaceTrendEvidence], args: argparse.Namespace) -> list[MarketplaceTrendEvidence]:
    records = collapse_duplicates(records)
    if args.marketplace:
        records = [item for item in records if item.marketplace == args.marketplace]
    candidate_ids = sorted({item.candidate_id for item in records})[: args.max_candidates]
    selected = [item for item in records if item.candidate_id in candidate_ids]
    grouped: dict[str, list[MarketplaceTrendEvidence]] = {}
    for item in selected:
        grouped.setdefault(item.candidate_id, []).append(item)
    return [item for candidate_id in sorted(grouped) for item in grouped[candidate_id][: args.max_sources_per_candidate]]


def markdown(report: dict) -> str:
    lines = [
        "# Marketplace Trend Intelligence",
        "",
        f"Evidence mode: `{report['evidence_mode']}` (offline; not supplier proof)",
        f"Candidates: {report['candidate_count']}",
        f"Sources: {report['source_count']}",
        f"Marketplaces: {', '.join(report['marketplaces_observed']) or 'none'}",
        f"Top candidate: `{report['top_candidate_id'] or 'none'}`",
        f"Next action: `{report['next_best_action']}`",
        "",
        "## Candidate scores",
        "",
        "| Candidate | Opportunity | Demand proxy | Saturation | Price confidence | Recommendation |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in report["candidates"]:
        score = item["score"]
        lines.append(
            f"| {item['candidate_id']} | {score['overall_marketplace_opportunity']:.0%} | "
            f"{score['demand_proxy_score']:.0%} | {score['saturation_score']:.0%} | "
            f"{score['price_confidence']:.0%} | `{score['recommendation']}` |"
        )
    lines += [
        "",
        "## Safety and interpretation",
        "",
        "- This run performs no network calls and no provider mutations.",
        "- Marketplace demand/competition signals are not supplier proof.",
        "- Supplier price, inventory, shipping, and delivery still require supplier evidence.",
        "",
        "## Warnings",
        "",
    ]
    lines.extend(f"- {warning}" for warning in report.get("warnings", []))
    return "\n".join(lines) + "\n"


def _write_output(directory: str, report: dict, markdown_text: str) -> None:
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    (target / "marketplace_trend_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (target / "marketplace_trend_report.md").write_text(markdown_text, encoding="utf-8")
    summary = {
        "marketplaces": report["marketplaces_observed"],
        "source_count": report["source_count"],
        "candidate_count": report["candidate_count"],
        "best_seller_evidence_count": report["best_seller_evidence_count"],
        "read_only": True,
        "network_calls": False,
        "mutated": False,
    }
    (target / "marketplace_source_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline, deterministic marketplace trend intelligence")
    parser.add_argument("--candidate-seed")
    parser.add_argument("--manual-import")
    parser.add_argument("--marketplace", choices=("amazon", "ebay", "mercadolibre", "alibaba", "aliexpress", "etsy", "walmart", "shopify", "woocommerce"))
    parser.add_argument("--max-candidates", type=int, default=10)
    parser.add_argument("--max-sources-per-candidate", type=int, default=8)
    parser.add_argument("--allow-network", action="store_true", help="reserved; this offline slice refuses network mode")
    parser.add_argument("--output")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)
    if args.json and args.markdown:
        parser.error("choose --json or --markdown")
    if args.allow_network:
        parser.error("network mode is not implemented in the offline slice; use existing public benchmark tooling")
    if args.max_candidates < 1 or args.max_sources_per_candidate < 1:
        parser.error("bounds must be positive")
    try:
        records = _bounded_records(_load_records(args), args)
    except (OSError, ValueError, json.JSONDecodeError, MarketplaceImportError) as exc:
        parser.error(str(exc))
    mode = "manual_import" if args.manual_import else "fixture_demo"
    report = build_report(records, evidence_mode=mode).to_dict()
    text = markdown(report)
    if args.output:
        _write_output(args.output, report, text)
    print(text if args.markdown else json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
