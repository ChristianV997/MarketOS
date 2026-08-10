"""Run the fixture-first advisory Commerce MVP packet; no provider calls."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from backend.events.repository import JsonlEventRepository
from backend.events.adapters.supabase_staging import build_supabase_staging_repository, explain_supabase_staging_readiness
from backend.events.supabase_event_validation import validate_events_for_supabase
from backend.ecommerce.shopify_readonly.events import append_shopify_events
from backend.ecommerce.shopify_readonly.importer import import_shopify_readonly
from backend.mvp_commerce.runner import run_commerce_mvp_slice


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a dry-run Commerce MVP packet from local fixture signals.")
    parser.add_argument("--fixture"); parser.add_argument("--query", required=True); parser.add_argument("--use-public-signal-fixture", action="store_true")
    parser.add_argument("--write-jsonl"); parser.add_argument("--shopify-fixture"); parser.add_argument("--write-supabase", action="store_true"); parser.add_argument("--supabase-dry-run", action="store_true"); parser.add_argument("--event-target", choices=("jsonl", "supabase", "both")); parser.add_argument("--require-supabase-config", action="store_true"); parser.add_argument("--json", action="store_true", dest="as_json"); parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--workspace-id", default="commerce-mvp-dry-run"); parser.add_argument("--assumed-price", type=float, default=49.0); parser.add_argument("--assumed-unit-cost", type=float, default=15.0); parser.add_argument("--assumed-shipping-cost", type=float, default=6.0); parser.add_argument("--assumed-cac", type=float, default=12.0); parser.add_argument("--assumed-return-rate", type=float, default=.08)
    args = parser.parse_args(argv)
    if args.markdown and args.as_json: raise SystemExit("choose --json or --markdown, not both")
    fixture = args.fixture or (ROOT / "tests/fixtures/public_signals/rss_sample.json" if args.use_public_signal_fixture else None)
    if not fixture: raise SystemExit("--fixture or --use-public-signal-fixture is required; network mode is intentionally not part of this command")
    wants_jsonl = bool(args.write_jsonl) or args.event_target in {"jsonl", "both"}
    wants_supabase = args.write_supabase or args.event_target in {"supabase", "both"}
    if wants_jsonl and not args.write_jsonl: parser.error("JSONL target requires --write-jsonl PATH")
    readiness = explain_supabase_staging_readiness()
    if args.require_supabase_config and not readiness["configured"]: parser.error("Supabase staging is not explicitly configured")
    repo = JsonlEventRepository(ROOT / args.write_jsonl) if wants_jsonl else None
    batch = context = None
    if args.shopify_fixture:
        batch, context = import_shopify_readonly(ROOT / args.shopify_fixture, args.workspace_id)
    run = run_commerce_mvp_slice(workspace_id=args.workspace_id, query=args.query, signal_fixture_path=fixture, assumed_price=args.assumed_price, assumed_unit_cost=args.assumed_unit_cost, assumed_shipping_cost=args.assumed_shipping_cost, assumed_cac=args.assumed_cac, assumed_return_rate=args.assumed_return_rate, write_repository=None, shopify_store_context=context)
    from backend.mvp_commerce.events import commerce_mvp_events
    from backend.ecommerce.shopify_readonly.events import shopify_batch_events
    events = ([*shopify_batch_events(batch, context)] if batch is not None else []) + commerce_mvp_events(run)
    supabase_result = {"requested": wants_supabase, "dry_run": args.supabase_dry_run, "readiness": readiness, "written_event_ids": []}
    if args.supabase_dry_run or wants_supabase:
        supabase_result["validation"] = validate_events_for_supabase(events)
    if wants_supabase:
        supabase_repo = build_supabase_staging_repository()
        supabase_result["written_event_ids"] = [item.event_id for item in supabase_repo.append_many(events)]
    if repo is not None: repo.append_many(events)
    if batch is not None and repo is not None:
        # Include every canonical event written by the operator-requested dual packet.
        from dataclasses import replace
        run = replace(run, canonical_event_ids=tuple(event.event_id for event in shopify_batch_events(batch, context)) + run.canonical_event_ids)
    if args.markdown: print(run.to_markdown())
    else:
        result = run.to_dict()
        if args.supabase_dry_run or wants_supabase or args.require_supabase_config: result["supabase_staging"] = supabase_result
        print(json.dumps(result, sort_keys=True, indent=2))
    return 0
if __name__ == "__main__": raise SystemExit(main())
