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
from backend.events.adapters.supabase_staging import build_supabase_staging_repository, explain_supabase_staging_readiness
from backend.events.supabase_event_validation import validate_events_for_supabase


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import a local Shopify-like export as read-only, PII-redacted advisory evidence.")
    parser.add_argument("--fixture", required=True); parser.add_argument("--workspace-id", default="commerce-mvp-dry-run")
    parser.add_argument("--limit", type=int); parser.add_argument("--write-jsonl"); parser.add_argument("--write-supabase", action="store_true"); parser.add_argument("--supabase-dry-run", action="store_true"); parser.add_argument("--event-target", choices=("jsonl", "supabase", "both")); parser.add_argument("--require-supabase-config", action="store_true"); parser.add_argument("--json", action="store_true", dest="as_json"); parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)
    if args.as_json and args.markdown: raise SystemExit("choose --json or --markdown, not both")
    wants_jsonl = bool(args.write_jsonl) or args.event_target in {"jsonl", "both"}; wants_supabase = args.write_supabase or args.event_target in {"supabase", "both"}
    if wants_jsonl and not args.write_jsonl: parser.error("JSONL target requires --write-jsonl PATH")
    readiness = explain_supabase_staging_readiness()
    if args.require_supabase_config and not readiness["configured"]: parser.error("Supabase staging is not explicitly configured")
    batch, context = import_shopify_readonly(ROOT / args.fixture, args.workspace_id, "fixture", args.limit)
    from backend.ecommerce.shopify_readonly.events import shopify_batch_events
    events = shopify_batch_events(batch, context); staging = {"requested": wants_supabase, "dry_run": args.supabase_dry_run, "readiness": readiness, "written_event_ids": []}
    if args.supabase_dry_run or wants_supabase: staging["validation"] = validate_events_for_supabase(events)
    if wants_supabase: staging["written_event_ids"] = [item.event_id for item in build_supabase_staging_repository().append_many(events)]
    if wants_jsonl: append_shopify_events(batch, context, JsonlEventRepository(ROOT / args.write_jsonl))
    if args.markdown: print(report_to_markdown(batch, context))
    else:
        report = report_to_dict(batch, context)
        if args.supabase_dry_run or wants_supabase or args.require_supabase_config: report["supabase_staging"] = staging
        print(json.dumps(report, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__": raise SystemExit(main())
