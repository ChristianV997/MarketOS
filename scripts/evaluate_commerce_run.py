"""Evaluate a Commerce Intelligence artifact or canonical event stream.

This command is read-only unless ``--write-evaluation-events`` is explicitly
provided. It never fetches public pages, calls providers, or changes runtime
decisions.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.commerce import compare_evaluations, evaluation_events, evaluate_input, load_evaluation_input


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Produce a deterministic Commerce Intelligence evaluation report.")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--artifact", help="validation_report.json or an artifact directory")
    source.add_argument("--jsonl", help="canonical event JSONL path")
    source.add_argument("--replay", help="replayable canonical event JSONL path")
    source.add_argument("--workspace", help="workspace/artifact directory containing validation_report.json/events.jsonl")
    parser.add_argument("--run-a", help="baseline artifact or event stream for comparison")
    parser.add_argument("--run-b", help="current artifact or event stream for comparison")
    parser.add_argument("--json", action="store_true", help="write JSON output")
    parser.add_argument("--markdown", action="store_true", help="write Markdown output")
    parser.add_argument("--output", help="optional output path; stdout remains the default")
    parser.add_argument("--write-evaluation-events", help="optional JSONL target for canonical evaluation events")
    return parser


def _markdown(report: dict) -> str:
    lines = [
        "# Commerce Intelligence Evaluation Report", "",
        f"- Report: `{report['report_id']}`", f"- Run: `{report['run_id']}`",
        f"- Input: `{report['input_kind']}`", f"- Events: `{report['event_count']}`",
        f"- Run quality: **{report['overall'].get('run_quality', 'unknown')}**", "",
        "## Engine metrics", "", "| Engine | Status | Samples | Key metrics |", "|---|---|---:|---|",
    ]
    for engine, value in report.get("engines", {}).items():
        metrics = value.get("metrics", {})
        key_metrics = ", ".join(f"{key}={item}" for key, item in sorted(metrics.items()) if isinstance(item, (int, float, str)) and key not in {"assumptions"})[:240]
        lines.append(f"| `{engine}` | `{value.get('status')}` | {value.get('sample_size', 0)} | {key_metrics} |")
    lines += ["", "## Overall", ""]
    lines.extend(f"- `{key}`: `{value}`" for key, value in sorted(report.get("overall", {}).items()))
    lines += ["", "## Reproducibility", "", f"- Reproducible: `{report['reproducibility']['reproducible']}`", f"- Replay hash digest: `{report['reproducibility']['replay_hash_digest']}`"]
    if report.get("comparison"):
        comparison = report["comparison"]
        lines += ["", "## Run comparison", "", f"- Baseline: `{comparison['baseline_run_id']}`", f"- Current: `{comparison['current_run_id']}`", f"- Ranking stability: `{comparison.get('ranking_stability')}`", f"- Improved metrics: `{len(comparison.get('improved_metrics', []))}`", f"- Worsened metrics: `{len(comparison.get('worsened_metrics', []))}`"]
    lines += ["", "## Safety", "", "- Read-only: `true`", "- Mutated: `false`", ""]
    return "\n".join(lines)


def _input_path(args: argparse.Namespace) -> tuple[str | None, str]:
    if args.artifact:
        return args.artifact, "artifact"
    if args.jsonl:
        return args.jsonl, "jsonl"
    if args.replay:
        return args.replay, "replay"
    if args.workspace:
        return args.workspace, "workspace"
    return None, "auto"


def _render(report: dict, *, markdown: bool) -> str:
    if markdown:
        return _markdown(report)
    return json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    path, source = _input_path(args)
    if not path and not (args.run_a and args.run_b):
        _parser().error("one input source or --run-a/--run-b is required")
    if bool(args.run_a) != bool(args.run_b):
        _parser().error("--run-a and --run-b must be supplied together")
    if args.json and args.markdown:
        _parser().error("choose --json or --markdown")
    if args.run_a and args.run_b:
        baseline = evaluate_input(load_evaluation_input(args.run_a, source="comparison_baseline"))
        current = evaluate_input(load_evaluation_input(args.run_b, source="comparison_current"))
        report = replace(current, comparison=compare_evaluations(baseline, current)).to_dict()
    else:
        current = evaluate_input(load_evaluation_input(path, source=source))
        report = current.to_dict()
    if args.write_evaluation_events:
        from backend.events.repository import JsonlEventRepository

        events = evaluation_events(current)
        JsonlEventRepository(Path(args.write_evaluation_events)).append_many(events)
        report["evaluation_event_count"] = len(events)
        report["evaluation_event_output"] = str(Path(args.write_evaluation_events))
    content = _render(report, markdown=args.markdown)
    if args.output:
        Path(args.output).write_text(content + ("" if content.endswith("\n") else "\n"), encoding="utf-8")
    else:
        print(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
