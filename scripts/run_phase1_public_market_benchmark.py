"""Run a bounded, read-only Phase 1 public-market evidence benchmark."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.commerce.public_market_benchmark import (
    build_public_market_benchmark,
    load_public_market_seed,
    markdown_report,
)

DEFAULT_SEED = ROOT / "tests" / "fixtures" / "public_market_benchmark" / "candidates.json"


def _write(output: str, report: dict[str, object], rendered: str) -> None:
    path = Path(output)
    if path.suffix:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return
    path.mkdir(parents=True, exist_ok=True)
    (path / "public_market_benchmark_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (path / "public_market_benchmark_report.md").write_text(rendered, encoding="utf-8")
    (path / "benchmark_matrix_report.json").write_text(json.dumps(report["benchmark_matrix"], indent=2, sort_keys=True) + "\n", encoding="utf-8")
    readiness = {
        "public_market_benchmark_status": report["evidence_mode"],
        "candidates_tested": report["candidates_tested"],
        "competitor_pages_attempted": report["competitor_pages_attempted"],
        "competitor_offers_observed": report["competitor_offers_observed"],
        "pricing_coverage": report["pricing_coverage"],
        "top_candidate_from_public_market": report["top_candidate_from_public_market"],
        "remaining_supplier_blocker": report["remaining_supplier_blocker"],
        "next_best_action": report["next_best_action"],
    }
    (path / "readiness_summary.json").write_text(json.dumps(readiness, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-seed", default=str(DEFAULT_SEED))
    parser.add_argument("--allow-network", action="store_true", help="Explicitly permit bounded public GETs.")
    parser.add_argument("--max-candidates", type=int, default=3)
    parser.add_argument("--max-competitors-per-candidate", type=int, default=3)
    parser.add_argument("--output", help="Optional sanitized output directory under artifacts/.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)
    if args.json and args.markdown:
        parser.error("choose --json or --markdown")
    candidates, warnings = load_public_market_seed(args.candidate_seed)
    report = build_public_market_benchmark(candidates, allow_network=args.allow_network, max_candidates=args.max_candidates, max_competitors_per_candidate=args.max_competitors_per_candidate).to_dict()
    report["warnings"] = sorted(set([*report["warnings"], *warnings]))
    rendered = markdown_report(report)
    if args.output:
        _write(args.output, report, rendered)
    print(rendered if args.markdown else json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
