"""Generate a deterministic, read-only Phase 1 readiness cockpit report."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.commerce.readiness import build_from_paths


def _markdown(value: dict) -> str:
    lines = ["# MarketOS Phase 1 Readiness", "", f"**Status:** `{value['overall_status']}`  ", f"**Score:** `{value['overall_score']}/100`  ", f"**Next action:** `{value['next_best_action']}`", "", "## Blocking gates", ""]
    lines.extend(f"- {item}" for item in value["blocking_gates"] or ["None encoded; advisory warnings may still apply."])
    lines += ["", "## Evidence", "", "| Area | Status | Signal |", "| --- | --- | --- |"]
    rows = (
        ("Supplier", value["supplier_readiness"], f"{value['supplier_readiness']['observed_field_count']} observed fields"),
        ("Competition", value["competition_readiness"], f"{value['competition_readiness']['observed_offer_count']} observed offers"),
        ("Commerce run", value["commerce_run_readiness"], value["commerce_run_readiness"]["run_quality"]),
        ("Evaluation", value["evaluation_readiness"], "comparison available" if value["evaluation_readiness"]["comparison_present"] else "structural framework available"),
        ("Events", value["event_readiness"], f"{value['event_readiness']['canonical_event_count']} canonical events"),
        ("Safety", value["safety_readiness"], "read-only/no-authority"),
    )
    lines.extend(f"| {name} | `{item['status']}` | {signal} |" for name, item, signal in rows)
    lines += ["", "## Operator guidance", "", value["next_best_prompt_hint"], "", "## Safety", "", "This report made no provider calls, did not read credential values, and did not mutate MarketOS or an external system."]
    if value["advisory_warnings"]:
        lines += ["", "## Advisory warnings", ""] + [f"- {item}" for item in value["advisory_warnings"]]
    return "\n".join(lines) + "\n"


def _write(output: str, value: dict, markdown: str) -> None:
    path = Path(output)
    if path.suffix:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return
    path.mkdir(parents=True, exist_ok=True)
    (path / "phase1_readiness_report.json").write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (path / "phase1_readiness_report.md").write_text(markdown, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validation-artifact")
    parser.add_argument("--evaluation-report")
    parser.add_argument("--comparison-report")
    parser.add_argument("--validation-pack-report")
    parser.add_argument("--output", help="explicit sanitized report destination; no output is written by default")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)
    if args.json and args.markdown:
        parser.error("choose --json or --markdown")
    report = build_from_paths(validation_artifact=args.validation_artifact, evaluation_report=args.evaluation_report, comparison_report=args.comparison_report, validation_pack_report=args.validation_pack_report).to_dict()
    markdown = _markdown(report)
    if args.output:
        _write(args.output, report, markdown)
    print(markdown if args.markdown else json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
