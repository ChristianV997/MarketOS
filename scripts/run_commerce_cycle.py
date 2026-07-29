#!/usr/bin/env python3
"""Run MarketOS's canonical commerce cycle on demand.

This is intentionally independent of FastAPI and defaults to dry-run.  Supply
JSON arrays/maps to replay a known batch, or omit them to use the configured
signal engine.  A live platform launch requires both ``--live`` and
``--confirm-live``.

Examples:
    python scripts/run_commerce_cycle.py
    python scripts/run_commerce_cycle.py --signals data/signals.json --top-k 3
    python scripts/run_commerce_cycle.py --signals data/signals.json --live --confirm-live
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _load_json(path: str | None, *, expected: type, label: str) -> Any:
    if path is None:
        return None
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, expected):
        raise ValueError(f"{label} must contain a JSON {expected.__name__}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the MarketOS commerce loop")
    parser.add_argument("--signals", help="Path to a JSON signal array; uses the configured signal engine when omitted")
    parser.add_argument("--products", help="Path to a JSON product map keyed by product id/name")
    parser.add_argument("--offers", help="Path to a JSON supplier-offer map keyed by product id/name")
    parser.add_argument("--top-k", type=int, default=5, help="Maximum opportunities to process (default: 5)")
    parser.add_argument("--budget", type=float, default=20.0, help="Per-campaign budget (default: 20.0)")
    parser.add_argument("--live", action="store_true", help="Execute platform launch calls instead of dry-run")
    parser.add_argument("--confirm-live", action="store_true", help="Required acknowledgement for --live")
    parser.add_argument("--output", help="Optional path to write the full cycle report as JSON")
    args = parser.parse_args()

    if args.live and not args.confirm_live:
        parser.error("--live requires --confirm-live")
    if args.top_k < 1:
        parser.error("--top-k must be at least 1")
    if args.budget < 0:
        parser.error("--budget cannot be negative")

    try:
        signals = _load_json(args.signals, expected=list, label="signals")
        products = _load_json(args.products, expected=dict, label="products")
        offers = _load_json(args.offers, expected=dict, label="offers")
        from backend.commerce import run_commerce_cycle

        report = run_commerce_cycle(
            signals=signals,
            products=products,
            offers=offers,
            top_k=args.top_k,
            budget=args.budget,
            dry_run=not args.live,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"commerce cycle input error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"commerce cycle failed: {exc}", file=sys.stderr)
        return 1

    payload = report.to_dict()
    print(json.dumps({
        "cycle_id": report.artifact_id,
        "dry_run": report.dry_run,
        "summary": report.summary,
    }, indent=2, default=str))
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        print(f"full report written to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
