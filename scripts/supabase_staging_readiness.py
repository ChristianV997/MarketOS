"""Read-only readiness report for optional canonical-event Supabase staging."""
from __future__ import annotations

import argparse, json, os, sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from backend.events.adapters.supabase_staging import explain_supabase_staging_readiness


def build_readiness(schema_path: str | Path = ROOT / "deploy/supabase/schema.sql", environ: dict[str, str] | None = None) -> dict[str, Any]:
    path = Path(schema_path); schema = path.read_text(encoding="utf-8") if path.is_file() else ""
    columns = ("event_id", "workspace_id", "aggregate_type", "aggregate_id", "event_type", "schema_version", "occurred_at", "payload", "metadata")
    return {"schema_path": str(path), "schema_present": path.is_file(), "canonical_events_table": "create table if not exists public.canonical_events" in schema.lower(), "required_columns_present": [column for column in columns if column in schema], "indexes_present": [name for name in ("canonical_events_workspace_occurred_idx", "canonical_events_event_type_idx", "canonical_events_aggregate_idx", "canonical_events_correlation_idx") if name in schema], "rls_enabled_or_documented": "alter table public.canonical_events enable row level security" in schema.lower(), "staging": explain_supabase_staging_readiness(environ), "service_role_warning": "SUPABASE_SERVICE_ROLE_KEY must stay server-side and is never a frontend/browser value.", "network_calls": False, "mutated": False, "next_actions": ["Apply reviewed schema to an operator-owned staging project.", "Keep JSONL default; use --supabase-dry-run before an explicit staging write."]}


def markdown_report(report: dict[str, Any]) -> str:
    return "\n".join(["# Supabase canonical-events staging readiness", "", f"- Schema present: `{report['schema_present']}`", f"- Canonical events table: `{report['canonical_events_table']}`", f"- Staging configured: `{report['staging']['configured']}`", f"- Gate enabled: `{report['staging']['write_gate_enabled']}`", "", "## Safety", "", f"- {report['service_role_warning']}", "- No network call or provider mutation was performed.", ""]) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__); output = parser.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true"); output.add_argument("--markdown", action="store_true"); parser.add_argument("--schema", default=str(ROOT / "deploy/supabase/schema.sql"))
    args = parser.parse_args(argv); report = build_readiness(args.schema, dict(os.environ))
    print(markdown_report(report) if args.markdown else json.dumps(report, sort_keys=True, indent=2)); return 0
if __name__ == "__main__": raise SystemExit(main())
