"""Build a PII-redacted Shopify manual import packet; never calls Shopify."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from backend.ecommerce.shopify_readonly.events import append_shopify_events
from backend.ecommerce.shopify_readonly.importer import import_shopify_readonly
from backend.ecommerce.shopify_readonly.reporting import report_to_dict, report_to_markdown
from backend.events.repository import JsonlEventRepository


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import a local Shopify-like export as read-only, PII-redacted advisory evidence.")
    parser.add_argument("--fixture", required=True); parser.add_argument("--workspace-id", default="commerce-mvp-dry-run")
    parser.add_argument("--limit", type=int); parser.add_argument("--write-jsonl"); parser.add_argument("--json", action="store_true", dest="as_json"); parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)
    if args.as_json and args.markdown: raise SystemExit("choose --json or --markdown, not both")
    batch, context = import_shopify_readonly(ROOT / args.fixture, args.workspace_id, "fixture", args.limit)
    if args.write_jsonl: append_shopify_events(batch, context, JsonlEventRepository(ROOT / args.write_jsonl))
    print(report_to_markdown(batch, context) if args.markdown else json.dumps(report_to_dict(batch, context), sort_keys=True, indent=2))
    return 0


if __name__ == "__main__": raise SystemExit(main())
