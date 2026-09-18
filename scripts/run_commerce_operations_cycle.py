"""Run the offline MarketOS commerce-operations readiness cycle."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.commerce.commerce_operations_cycle import (  # noqa: E402
    build_commerce_operations_cycle,
    reject_unsafe_input,
)
from scripts.run_product_opportunity_synthesis import _default_reports  # noqa: E402

def _read(path: str | None, *, label: str) -> dict[str, Any] | None:
    if not path:
        return None
    target = Path(path)
    path_parts = path.replace("\\", "/").split("/")
    if ".." in target.parts or ".." in path_parts or target.suffix.lower() != ".json":
        raise ValueError("only local JSON report paths without traversal are supported")
    if not target.is_file():
        raise ValueError(f"{label} does not exist: {target}")
    try:
        value = json.loads(target.read_text(encoding="utf8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"malformed JSON in {label}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    reject_unsafe_input(value, label=label)
    return value


def _write_output(directory: str, report: dict[str, Any], markdown_text: str) -> None:
    target = Path(directory)
    if ".." in target.parts or ".." in directory.replace("\\", "/").split("/"):
        raise ValueError("output traversal is not allowed")
    target.mkdir(parents=True, exist_ok=True)
    (target / "commerce_operations_cycle_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf8"
    )
    (target / "commerce_operations_cycle_report.md").write_text(markdown_text, encoding="utf8")
    (target / "client_safe_projection.json").write_text(
        json.dumps(report.get("client_safe_projection") or {}, indent=2, sort_keys=True) + "\n", encoding="utf8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline MarketOS commerce-operations readiness cycle")
    parser.add_argument("--marketplace-trend-report")
    parser.add_argument("--supplier-feasibility-report")
    parser.add_argument("--consumer-attention-report")
    parser.add_argument("--output")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--live", action="store_true", help="Rejected: live mode is not implemented and fail-closes as blocked")
    args = parser.parse_args(argv)
    if args.json and args.markdown:
        parser.error("choose --json or --markdown")
    try:
        if any((args.marketplace_trend_report, args.supplier_feasibility_report, args.consumer_attention_report)):
            market = _read(args.marketplace_trend_report, label="marketplace report")
            supplier = _read(args.supplier_feasibility_report, label="supplier report")
            consumer = _read(args.consumer_attention_report, label="consumer report")
        else:
            market, supplier, consumer = _default_reports()
            reject_unsafe_input(market, label="marketplace report")
            reject_unsafe_input(supplier, label="supplier report")
            reject_unsafe_input(consumer, label="consumer report")
        cycle = build_commerce_operations_cycle(market, supplier, consumer, live_requested=args.live)
        report = cycle.to_dict()
        if args.output:
            report["artifacts_written"] = True
            report["safety_summary"] = dict(report["safety_summary"])
            report["safety_summary"]["artifacts_written"] = True
            _write_output(args.output, report, cycle.to_markdown())
        print(cycle.to_markdown() if args.markdown else json.dumps(report, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"commerce_operations_cycle_error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
