"""Read canonical events from local JSONL or explicit Supabase staging; never writes."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from backend.events.query_models import EventQuery
from backend.events.query_service import event_query_report, load_events_from_jsonl
from backend.events.supabase_query_service import query_supabase_canonical_events
from backend.events.supabase_query_service import explain_supabase_readiness
from backend.events.adapters.supabase import SupabaseEventRepositoryError

def _markdown(report: dict) -> str:
    timeline = report["timeline"]; lines = ["# Canonical event read view", "", f"- Source: `{report.get('source', 'jsonl')}`", f"- Events: {len(timeline['events'])}", f"- Warnings: {', '.join(timeline['warnings']) or 'none'}", "", "## Event types", ""]
    lines += [f"- `{key}`: {value}" for key, value in timeline["event_type_counts"].items()]
    return "\n".join(lines) + "\n"

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__); source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--jsonl"); source.add_argument("--supabase-staging", action="store_true")
    parser.add_argument("--workspace-id"); parser.add_argument("--event-type"); parser.add_argument("--aggregate-type"); parser.add_argument("--aggregate-id"); parser.add_argument("--correlation-id"); parser.add_argument("--source-name"); parser.add_argument("--limit", type=int, default=100); parser.add_argument("--offset", type=int, default=0); parser.add_argument("--sort", choices=("asc", "desc"), default="asc")
    view = parser.add_mutually_exclusive_group(); view.add_argument("--timeline", action="store_true"); view.add_argument("--commerce-runs", action="store_true"); view.add_argument("--shopify-imports", action="store_true")
    output = parser.add_mutually_exclusive_group(); output.add_argument("--json", action="store_true"); output.add_argument("--markdown", action="store_true"); parser.add_argument("--output")
    args = parser.parse_args(argv); query = EventQuery(args.workspace_id, args.event_type, args.aggregate_type, args.aggregate_id, args.correlation_id, args.source_name, args.limit, args.offset, None, None, args.sort)
    if args.supabase_staging:
        try: report = query_supabase_canonical_events(query); report["warnings"] = []
        except SupabaseEventRepositoryError as exc:
            report = {"timeline": {"events": [], "event_type_counts": {}, "aggregate_type_counts": {}, "warnings": [str(exc)]}, "commerce_runs": [], "shopify_imports": [], "source": "supabase_staging", "readiness": explain_supabase_readiness(), "read_only": True, "network_calls": False, "mutated": False, "warnings": ["supabase_read_unavailable"]}
    else:
        events, warnings = load_events_from_jsonl(ROOT / args.jsonl); report = event_query_report(events, query, warnings); report["source"] = "jsonl"
    if args.commerce_runs: payload = {"commerce_runs": report["commerce_runs"], "warnings": report["timeline"]["warnings"], "read_only": True}
    elif args.shopify_imports: payload = {"shopify_imports": report["shopify_imports"], "warnings": report["timeline"]["warnings"], "read_only": True}
    else: payload = report
    rendered = _markdown(report) if args.markdown else json.dumps(payload, sort_keys=True, indent=2) + "\n"
    if args.output:
        target = (ROOT / args.output).resolve(); artifacts = (ROOT / "artifacts").resolve()
        if target != artifacts and artifacts not in target.parents: parser.error("--output must stay under artifacts/")
        target.parent.mkdir(parents=True, exist_ok=True); target.write_text(rendered, encoding="utf-8")
    print(rendered, end=""); return 0
if __name__ == "__main__": raise SystemExit(main())
