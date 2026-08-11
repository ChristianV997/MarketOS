"""Run offline supplier feasibility intelligence from sanitized snapshots/imports."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.adapters.research.supplier_feasibility import (  # noqa: E402
    SupplierImportError,
    import_csv,
    import_json,
)
from evaluation.commerce.supplier_feasibility import SupplierFeasibilityEvidence, build_report, collapse_duplicates  # noqa: E402

DEFAULT = ROOT / "tests" / "fixtures" / "supplier_feasibility" / "cj_validation_pack_success.json"
SUPPLIERS = ("cj", "alibaba", "aliexpress", "zendrop", "autods", "dsers", "spocket", "manual")


def markdown(report: dict) -> str:
    lines = [
        "# Supplier Feasibility Intelligence",
        "",
        f"Evidence mode: `{report['evidence_mode']}` (offline; not supplier authorization)",
        f"Candidates: {report['candidate_count']}",
        f"Offers: {report['offer_count']}",
        f"Suppliers: {', '.join(report['suppliers_observed']) or 'none'}",
        f"Top candidate: `{report['top_candidate_id'] or 'none'}`",
        f"Next action: `{report['next_best_action']}`",
        "",
        "## Feasibility scores",
        "",
        "| Candidate | Feasibility | Cost confidence | Logistics risk | Margin proxy | Recommendation |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in report["candidates"]:
        score = item["score"]
        lines.append(
            f"| {item['candidate_id']} | {score['overall_supplier_feasibility']:.0%} | "
            f"{score['supplier_cost_confidence']:.0%} | {score['delivery_risk_score']:.0%} | "
            f"{score['margin_feasibility_proxy']:.0%} | `{score['recommendation']}` |"
        )
    lines += [
        "",
        "## Interpretation",
        "",
        "- Supplier feasibility is sourcing evidence, not an order or fulfillment instruction.",
        "- Fixture and manual-import values are not live credential-validated proof.",
        "- Missing shipping, delivery, inventory, or landed cost remains an explicit risk.",
        "",
        "## Warnings",
        "",
    ]
    lines.extend(f"- {warning}" for warning in report.get("warnings", []))
    return "\n".join(lines) + "\n"


def _bounded(records: list[SupplierFeasibilityEvidence], args: argparse.Namespace) -> list[SupplierFeasibilityEvidence]:
    records = collapse_duplicates(records)
    if args.supplier:
        records = [record for record in records if record.supplier == args.supplier]
    candidate_ids = sorted({record.candidate_id for record in records})[: args.max_candidates]
    return [record for record in records if record.candidate_id in candidate_ids]


def _write_output(directory: str, report: dict, text: str) -> None:
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    (target / "supplier_feasibility_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf8")
    (target / "supplier_feasibility_report.md").write_text(text, encoding="utf8")
    summary = {
        "suppliers": report["suppliers_observed"],
        "candidate_count": report["candidate_count"],
        "offer_count": report["offer_count"],
        "read_only": True,
        "network_calls": False,
        "mutated": False,
    }
    (target / "supplier_source_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline supplier feasibility intelligence")
    parser.add_argument("--candidate-seed")
    parser.add_argument("--manual-import")
    parser.add_argument("--supplier", choices=SUPPLIERS)
    parser.add_argument("--max-candidates", type=int, default=10)
    parser.add_argument("--target-sell-price", type=float, action="append", help="optional scenario price applied to all candidates")
    parser.add_argument("--output")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)
    if args.json and args.markdown:
        parser.error("choose --json or --markdown")
    if args.max_candidates < 1:
        parser.error("max-candidates must be positive")
    try:
        records = import_csv(args.manual_import, supplier=args.supplier or "manual") if args.manual_import else import_json(args.candidate_seed or DEFAULT, supplier=args.supplier or "cj", source_type="cj_validation_pack_report" if not args.candidate_seed else "fixture_demo")
        records = _bounded(records, args)
    except (OSError, ValueError, json.JSONDecodeError, SupplierImportError) as exc:
        parser.error(str(exc))
    prices = {record.candidate_id: args.target_sell_price[0] for record in records} if args.target_sell_price else None
    report = build_report(records, evidence_mode="manual_import" if args.manual_import else "fixture_demo", target_sell_prices=prices).to_dict()
    text = markdown(report)
    if args.output:
        _write_output(args.output, report, text)
    print(text if args.markdown else json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
