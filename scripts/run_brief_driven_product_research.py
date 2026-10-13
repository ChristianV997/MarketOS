"""CLI for brief-driven offline product-opportunity research.

Accepts a minimal research brief, derives source queries, invokes injectable
offline/fake source clients through existing normalize/build_report contracts,
and reuses Product Opportunity Synthesis for the decision layer.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.commerce.brief_driven_research import (  # noqa: E402
    ResearchBrief,
    render_markdown,
    run_brief_driven_research,
)


def _output_path(value: str) -> Path:
    raw = Path(value)
    if ".." in raw.parts:
        raise ValueError("output traversal is not accepted")
    path = raw if raw.is_absolute() else ROOT / raw
    return path.resolve()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product-query", required=True)
    parser.add_argument("--category", required=True)
    parser.add_argument("--region", required=True, help="Target region / market")
    parser.add_argument("--language", required=True)
    parser.add_argument("--intended-buyer", required=True)
    parser.add_argument("--max-candidates", type=int, default=5)
    parser.add_argument("--workspace-id", default="")
    parser.add_argument(
        "--use-fixture-demo",
        action="store_true",
        help="Use offline fixture-demo source clients derived from the brief (default: sources not_configured).",
    )
    parser.add_argument("--timeout-seconds", type=float, default=2.0)
    parser.add_argument("--max-concurrency", type=int, default=1)
    parser.add_argument("--output")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)
    if args.json and args.markdown:
        parser.error("choose --json or --markdown")
    try:
        brief = ResearchBrief(
            product_query=args.product_query,
            category=args.category,
            target_region=args.region,
            language=args.language,
            intended_buyer=args.intended_buyer,
            max_candidates=args.max_candidates,
            workspace_id=args.workspace_id,
        )
        report = run_brief_driven_research(
            brief,
            use_default_fixture_clients=args.use_fixture_demo,
            timeout_s=args.timeout_seconds,
            max_concurrency=args.max_concurrency,
            allow_live=False,
        )
        payload = report.to_dict()
        markdown = render_markdown(report)
        if args.output:
            out = _output_path(args.output)
            out.mkdir(parents=True, exist_ok=True)
            (out / "brief_driven_research_report.json").write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            (out / "brief_driven_research_report.md").write_text(markdown, encoding="utf-8")
        print(markdown if args.markdown else json.dumps(payload, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"brief_driven_research_error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
