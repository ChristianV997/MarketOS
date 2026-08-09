"""Emit deterministic, read-only shadow feature evaluation reports."""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.evaluation.shadow_features.evaluator import build_shadow_evaluation_report
from backend.evaluation.shadow_features.fixtures import default_fixture_paths
from backend.evaluation.shadow_features.reporting import report_to_json, report_to_markdown


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", action="store_true", help="evaluate committed synthetic fixtures")
    parser.add_argument("--path", action="append", default=[], help="canonical JSONL input; may be repeated")
    parser.add_argument("--feature", action="append", default=[], help="only include a feature ID; may be repeated")
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true", help="emit canonical JSON report")
    output.add_argument("--markdown", action="store_true", help="emit Markdown report")
    parser.add_argument("--output", help="optional report output path; no state is changed")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    paths = [Path(item) for item in args.path]
    if args.fixtures or not paths:
        paths.extend(default_fixture_paths())
    absent = [str(path) for path in paths if not path.is_file()]
    if absent:
        print(f"invalid input path(s): {', '.join(absent)}", file=sys.stderr)
        return 2
    try:
        report = build_shadow_evaluation_report(paths)
    except Exception as exc:
        print(f"evaluation failed: {exc}", file=sys.stderr)
        return 1
    if args.feature:
        selected = set(args.feature)
        features = [item for item in report.features if item.feature_id in selected]
        counts = Counter(item.classification for item in features)
        report = replace(report, features=features, summary_counts={key: counts.get(key, 0) for key in report.summary_counts})
    content = report_to_markdown(report) if args.markdown else report_to_json(report)
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    print(content, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
