"""Run the fixture-first advisory Commerce MVP packet; no provider calls."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from backend.events.repository import JsonlEventRepository
from backend.ecommerce.shopify_readonly.events import append_shopify_events
from backend.ecommerce.shopify_readonly.importer import import_shopify_readonly
from backend.mvp_commerce.runner import run_commerce_mvp_slice


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a dry-run Commerce MVP packet from local fixture signals.")
    parser.add_argument("--fixture"); parser.add_argument("--query", required=True); parser.add_argument("--use-public-signal-fixture", action="store_true")
    parser.add_argument("--write-jsonl"); parser.add_argument("--shopify-fixture"); parser.add_argument("--json", action="store_true", dest="as_json"); parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--workspace-id", default="commerce-mvp-dry-run"); parser.add_argument("--assumed-price", type=float, default=49.0); parser.add_argument("--assumed-unit-cost", type=float, default=15.0); parser.add_argument("--assumed-shipping-cost", type=float, default=6.0); parser.add_argument("--assumed-cac", type=float, default=12.0); parser.add_argument("--assumed-return-rate", type=float, default=.08)
    args = parser.parse_args(argv)
    if args.markdown and args.as_json: raise SystemExit("choose --json or --markdown, not both")
    fixture = args.fixture or (ROOT / "tests/fixtures/public_signals/rss_sample.json" if args.use_public_signal_fixture else None)
    if not fixture: raise SystemExit("--fixture or --use-public-signal-fixture is required; network mode is intentionally not part of this command")
    repo = JsonlEventRepository(ROOT / args.write_jsonl) if args.write_jsonl else None
    batch = context = None
    if args.shopify_fixture:
        batch, context = import_shopify_readonly(ROOT / args.shopify_fixture, args.workspace_id)
        if repo is not None: append_shopify_events(batch, context, repo)
    run = run_commerce_mvp_slice(workspace_id=args.workspace_id, query=args.query, signal_fixture_path=fixture, assumed_price=args.assumed_price, assumed_unit_cost=args.assumed_unit_cost, assumed_shipping_cost=args.assumed_shipping_cost, assumed_cac=args.assumed_cac, assumed_return_rate=args.assumed_return_rate, write_repository=repo, shopify_store_context=context)
    if batch is not None and repo is not None:
        # Include every canonical event written by the operator-requested dual packet.
        from dataclasses import replace
        from backend.ecommerce.shopify_readonly.events import shopify_batch_events
        run = replace(run, canonical_event_ids=tuple(event.event_id for event in shopify_batch_events(batch, context)) + run.canonical_event_ids)
    print(run.to_markdown() if args.markdown else json.dumps(run.to_dict(), sort_keys=True, indent=2) )
    return 0
if __name__ == "__main__": raise SystemExit(main())
