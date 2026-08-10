"""Read-only SaaS Capability Router report for MarketOS.

The script uses static catalog metadata only. It never resolves credentials,
contacts providers, starts jobs, or changes an integration state.
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

from backend.providers.vendor_router import report_to_dict, report_to_markdown


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render the read-only MarketOS vendor capability plan.")
    parser.add_argument("--stage", default="mvp", choices=("mvp", "evaluation"))
    parser.add_argument("--capability")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--output", help="Optional relative artifact report path.")
    return parser


def render(args: argparse.Namespace) -> str:
    if args.markdown:
        return report_to_markdown(args.stage, args.capability)
    report: dict[str, Any] = report_to_dict(args.stage, args.capability)
    return json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.as_json and args.markdown:
        raise SystemExit("choose --json or --markdown, not both")
    payload = render(args)
    if args.output:
        output = (ROOT / args.output).resolve()
        artifacts_root = (ROOT / "artifacts").resolve()
        if artifacts_root not in output.parents:
            raise SystemExit("--output must remain under artifacts/")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
