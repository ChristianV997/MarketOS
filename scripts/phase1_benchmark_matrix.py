"""Generate the read-only Phase 1 Evidence Benchmark Matrix."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from evaluation.commerce.benchmark_matrix import build_benchmark_from_paths

def markdown(report: dict) -> str:
    lines = ["# Phase 1 Evidence Benchmark Matrix", "", f"**Mode:** `{report['evidence_mode']}`  ", f"**Top candidate:** `{report['top_candidate_id']}`  ", f"**Next action:** `{report['next_best_action']}`", "", "| Candidate | Evidence | Risk | Decision | Validation priority | Next action |", "| --- | ---: | --- | --- | --- | --- |"]
    for item in report["candidates"]:
        candidate = item["candidate"]
        lines.append(f"| {candidate['title']} | {item['evidence_completeness']:.2f} | {item['risk_level']} | `{item['commercial_decision']}` | {item['validation_priority']['priority']} ({item['validation_priority']['target']}) | `{item['next_best_action']}` |")
    lines += ["", "Fixture/demo evidence is explicitly non-live. This workbench does not validate, call providers, or authorize commercial actions."]
    if report["warnings"]: lines += ["", "## Warnings", ""] + [f"- {item}" for item in report["warnings"]]
    return "\n".join(lines) + "\n"

def write(output: str, report: dict, rendered: str) -> None:
    path = Path(output)
    if path.suffix:
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"); return
    path.mkdir(parents=True, exist_ok=True)
    (path / "benchmark_matrix_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (path / "benchmark_matrix_report.md").write_text(rendered, encoding="utf-8")

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-seed"); parser.add_argument("--readiness-report"); parser.add_argument("--evaluation-report"); parser.add_argument("--output")
    parser.add_argument("--json", action="store_true"); parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)
    if args.json and args.markdown: parser.error("choose --json or --markdown")
    report = build_benchmark_from_paths(candidate_seed=args.candidate_seed, readiness_report=args.readiness_report, evaluation_report=args.evaluation_report).to_dict()
    rendered = markdown(report)
    if args.output: write(args.output, report, rendered)
    print(rendered if args.markdown else json.dumps(report, indent=2, sort_keys=True))
    return 0
if __name__ == "__main__": raise SystemExit(main())
