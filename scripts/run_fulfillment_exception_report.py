"""Print one offline fulfillment-exception review. It does not take an action."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.commerce.fulfillment_exception_report import (
    SCHEMA,
    SCENARIO_NAMES,
    build_failed_delivery_fixture,
    render_markdown,
    review_fixture_queue,
    review_named_fixture,
    review_proposed_path,
    review_scenario,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=SCENARIO_NAMES)
    parser.add_argument("--all-fixtures", action="store_true")
    parser.add_argument("--failed-delivery-fixture", action="store_true")
    parser.add_argument("--path", help="comma-separated fulfillment states, including illegal proposals")
    parser.add_argument("--order-id", default="order-proposed-path")
    parser.add_argument("--reviewed-at", required=True)
    parser.add_argument("--max-evidence-age-hours", type=int, default=168)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--exceptions-only", action="store_true")
    args = parser.parse_args(argv)
    selected = sum(bool(item) for item in (args.scenario, args.all_fixtures, args.failed_delivery_fixture, args.path))
    if selected != 1 or (args.as_json and args.markdown):
        print(json.dumps({"schema": SCHEMA, "overall": "malformed", "error": "invalid review input"}), file=sys.stderr)
        return 2
    try:
        if args.all_fixtures:
            document = review_fixture_queue(
                reviewed_at=args.reviewed_at,
                max_evidence_age_hours=args.max_evidence_age_hours,
            )
        elif args.failed_delivery_fixture:
            scenario, adapter = build_failed_delivery_fixture()
            document = review_scenario(
                scenario,
                reviewed_at=args.reviewed_at,
                adapter=adapter,
                max_evidence_age_hours=args.max_evidence_age_hours,
            )
        elif args.path is not None:
            document = review_proposed_path(
                tuple(part.strip() for part in args.path.split(",")),
                order_id=args.order_id,
                reviewed_at=args.reviewed_at,
            )
        else:
            document = review_named_fixture(
                args.scenario,
                reviewed_at=args.reviewed_at,
                max_evidence_age_hours=args.max_evidence_age_hours,
            )
    except ValueError:
        print(json.dumps({"schema": SCHEMA, "overall": "malformed", "error": "invalid review input"}), file=sys.stderr)
        return 2
    if args.exceptions_only and document.get("mode") == "queue":
        document = dict(document)
        document["decisions"] = [item for item in document["decisions"] if item.get("attention_required")]
        document["filtered_to_exceptions"] = True
    if args.markdown:
        print(render_markdown(document, exceptions_only=args.exceptions_only))
    else:
        print(json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
