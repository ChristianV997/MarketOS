#!/usr/bin/env python3
"""Offline CLI for services.research_query_plan.

Reads a JSON brief from --brief or stdin and writes a research-query-plan-v1
packet. No provider calls, credentials, or network I/O.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.research_query_plan import build_research_query_plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brief", type=Path, help="Path to a product brief JSON file")
    parser.add_argument("--output", type=Path, help="Optional output path (default: stdout)")
    args = parser.parse_args(argv)

    if args.brief is not None:
        payload = json.loads(args.brief.read_text(encoding="utf-8"))
    else:
        payload = json.load(sys.stdin)

    plan = build_research_query_plan(payload)
    text = json.dumps(plan.to_dict(), ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0 if plan.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
