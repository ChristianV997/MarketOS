"""Run an advisory Commerce MVP packet from fixtures or public Google News RSS."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.ecommerce.shopify_readonly.events import shopify_batch_events
from backend.ecommerce.shopify_readonly.importer import import_shopify_readonly
from backend.events.adapters.supabase_staging import build_supabase_staging_repository, explain_supabase_staging_readiness
from backend.events.repository import JsonlEventRepository
from backend.events.supabase_event_validation import validate_events_for_supabase
from backend.mvp_commerce.events import commerce_mvp_events
from backend.mvp_commerce.public_run import run_commerce_mvp_from_public_rss
from backend.mvp_commerce.runner import run_commerce_mvp_slice


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build an advisory Commerce MVP packet from fixtures or a gated public RSS query.")
    parser.add_argument("--fixture")
    parser.add_argument("--query")
    parser.add_argument("--public-query")
    parser.add_argument("--allow-public-network", action="store_true")
    parser.add_argument("--public-cache-dir", default=None)
    parser.add_argument("--use-public-signal-fixture", action="store_true")
    parser.add_argument("--max-signals", type=int, default=10)
    parser.add_argument("--max-candidates", type=int, default=5)
    parser.add_argument("--write-jsonl")
    parser.add_argument("--write-supabase", action="store_true")
    parser.add_argument("--supabase-dry-run", action="store_true")
    parser.add_argument("--event-target", choices=("none", "jsonl", "supabase_staging", "both", "supabase"), default=None)
    parser.add_argument("--require-supabase-config", action="store_true")
    parser.add_argument("--shopify-fixture")
    parser.add_argument("--operator-note", default="")
    parser.add_argument("--workspace-id", default="commerce-mvp-dry-run")
    parser.add_argument("--assumed-price", type=float, default=49.0)
    parser.add_argument("--assumed-unit-cost", type=float, default=15.0)
    parser.add_argument("--assumed-shipping-cost", type=float, default=6.0)
    parser.add_argument("--assumed-cac", type=float, default=12.0)
    parser.add_argument("--assumed-return-rate", type=float, default=.08)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--markdown", action="store_true")
    return parser


def _target_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> tuple[bool, bool]:
    wants_jsonl = bool(args.write_jsonl) or args.event_target in {"jsonl", "both"}
    wants_supabase = args.write_supabase or args.event_target in {"supabase", "supabase_staging", "both"}
    if wants_jsonl and not args.write_jsonl:
        parser.error("JSONL target requires --write-jsonl PATH")
    return wants_jsonl, wants_supabase


def _economics(args: argparse.Namespace) -> dict[str, float]:
    return {
        "assumed_price": args.assumed_price,
        "assumed_unit_cost": args.assumed_unit_cost,
        "assumed_shipping_cost": args.assumed_shipping_cost,
        "assumed_cac": args.assumed_cac,
        "assumed_return_rate": args.assumed_return_rate,
    }


def _fixture_path(args: argparse.Namespace) -> str | None:
    if args.fixture:
        return args.fixture
    if args.use_public_signal_fixture:
        return "tests/fixtures/commerce_mvp/public_signals.json"
    return None


def _write_reports(args: argparse.Namespace, report: dict[str, Any]) -> None:
    if args.markdown:
        run = report.get("run", report)
        print("# Commerce MVP public run" if report.get("public_source_status") else "# Commerce MVP packet")
        print()
        print(f"- Status: `{report.get('public_source_status', run.get('status', 'unknown'))}`")
        print(f"- Signals: {report.get('signal_count', len(run.get('signal_batch', [])))}")
        print(f"- Candidate: `{report.get('selected_candidate') or run.get('selected_candidate', {}).get('product_name', 'none')}`")
        print(f"- Events: {report.get('event_count', len(run.get('canonical_event_ids', [])))}")
        print()
        print("- Advisory only; no provider, store, ad, payment, fulfillment, or publishing action was executed.")
        for warning in report.get("warnings", []):
            print(f"- Warning: {warning}")
        return
    print(json.dumps(report, sort_keys=True, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.markdown and args.as_json:
        parser.error("choose --json or --markdown, not both")
    query = (args.public_query or args.query or "").strip()
    if not query:
        parser.error("--query or --public-query is required")
    public_mode = bool(args.public_query)
    fixture = _fixture_path(args)
    if not public_mode and not fixture:
        parser.error("--fixture, --use-public-signal-fixture, or --public-query is required")
    if public_mode and args.fixture:
        parser.error("--public-query cannot be combined with --fixture")
    if args.max_signals < 1 or args.max_candidates < 1:
        parser.error("--max-signals and --max-candidates must be positive")

    wants_jsonl, wants_supabase = _target_args(args, parser)
    readiness = explain_supabase_staging_readiness()
    if args.require_supabase_config and not readiness["configured"]:
        parser.error("Supabase staging is not explicitly configured")
    if wants_supabase and args.supabase_dry_run is False and not readiness["configured"]:
        parser.error("Supabase writes require SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, and MARKETOS_SUPABASE_CANONICAL_EVENTS=1")

    batch = context = None
    if args.shopify_fixture:
        batch, context = import_shopify_readonly(ROOT / args.shopify_fixture, args.workspace_id)

    common = {
        "workspace_id": args.workspace_id,
        "query": query,
        "max_signals": args.max_signals,
        "max_candidates": args.max_candidates,
        "shopify_store_context": context,
        **_economics(args),
    }
    if public_mode:
        cache_dir = args.public_cache_dir or os.getenv("MARKETOS_PUBLIC_SIGNAL_CACHE_DIR") or str(ROOT / "artifacts/public-signal-cache")
        result = run_commerce_mvp_from_public_rss(
            **common,
            allow_network=args.allow_public_network,
            cache_dir=cache_dir,
            operator_note=args.operator_note,
        )
        events = list(result.events)
        report = result.to_dict()
    else:
        run = run_commerce_mvp_slice(**common, signal_fixture_path=ROOT / fixture, write_repository=None, mode="fixture")
        events = commerce_mvp_events(run)
        report = run.to_dict()
        report["public_source_status"] = "fixture"
        report["network_used"] = False
        report["cache_status"] = "fixture"
        report["signal_count"] = len(run.signal_batch)
        report["candidate_count"] = len(run.opportunity_candidates)
        report["selected_candidate"] = run.selected_candidate.product_name if run.selected_candidate else None
        report["event_count"] = len(events)
        report["event_type_counts"] = {event.event_type: sum(item.event_type == event.event_type for item in events) for event in events}
        report["write_targets"] = []
        report["read_only"] = True
        report["advisory"] = True
        report["mutated"] = False

    if batch is not None:
        events = shopify_batch_events(batch, context) + events
        report["event_count"] = len(events)
        report["event_type_counts"] = dict(sorted({event.event_type: sum(item.event_type == event.event_type for item in events) for event in events}.items()))

    targets: list[str] = []
    if wants_jsonl:
        JsonlEventRepository(ROOT / args.write_jsonl).append_many(events)
        targets.append("jsonl")
    supabase_result: dict[str, Any] | None = None
    if args.supabase_dry_run or wants_supabase:
        validation = validate_events_for_supabase(events)
        supabase_result = {"requested": wants_supabase, "dry_run": args.supabase_dry_run, "readiness": readiness, "validation": validation, "written_event_ids": []}
    if wants_supabase and not args.supabase_dry_run:
        repository = build_supabase_staging_repository()
        supabase_result["written_event_ids"] = [item.event_id for item in repository.append_many(events)]
        targets.append("supabase_staging")
    report["write_targets"] = targets
    if supabase_result is not None:
        report["supabase_staging"] = supabase_result
    _write_reports(args, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
