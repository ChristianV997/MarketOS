#!/usr/bin/env python3
"""Print offline consumer-attention insights from normalized evidence JSON.

Reads a consumer-attention report or a list of normalized evidence rows.
Does not collect data, read credentials, call providers, or write a client file.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.commerce.consumer_attention_insights import (  # noqa: E402
    build_consumer_attention_insights,
    render_consumer_attention_insights_markdown,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Synthesize offline consumer-attention insights.")
    parser.add_argument("path", nargs="?", help="Normalized evidence JSON. Reads stdin when omitted.")
    parser.add_argument("--as-of", default=None, help="Explicit ISO-8601 reference time. Never uses the host clock.")
    parser.add_argument("--freshness-days", type=int, default=90)
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--output", default=None, help="Optional sanitized report path. Default is stdout only.")
    args = parser.parse_args()
    raw = Path(args.path).read_text(encoding="utf-8") if args.path else sys.stdin.read()
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError:
        print(json.dumps({"status": "blocked", "warnings": ["invalid_request"]}))
        return 2
    try:
        report = build_consumer_attention_insights(payload, as_of=args.as_of, max_age_days=args.freshness_days)
    except (TypeError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "warnings": [str(exc).split(":", 1)[0] or "invalid_request"]}))
        return 2
    body = report.to_dict()
    rendered = render_consumer_attention_insights_markdown(body) if args.markdown else json.dumps(body, sort_keys=True)
    if args.output:
        destination = Path(args.output)
        if destination.is_absolute() or ".." in destination.parts:
            print(json.dumps({"status": "blocked", "warnings": ["unsafe_output_path"]}))
            return 2
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered if args.markdown else json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sys.stdout.write(rendered if rendered.endswith("\n") else rendered + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
