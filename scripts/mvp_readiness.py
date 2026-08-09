"""Read-only deployment readiness report for the MarketOS MVP Island."""
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

from backend.runtime.mvp_mode import PROFILE_PATH, load_mvp_profile, mvp_readiness_report


REQUIRED_FILES = (
    "deploy/mvp/marketos.mvp.json", "deploy/mvp/.env.mvp.example", "deploy/supabase/schema.sql",
    "deploy/supabase/README.md", "docs/MVP_ISLAND.md", "docs/SAAS_INTEGRATION_SCORECARD.md",
    "deploy/vercel/README.md", "deploy/railway/README.md", "deploy/render/README.md",
    "frontend/package.json", "backend/api.py",
)


def build_mvp_readiness(environ: dict[str, str] | None = None) -> dict[str, Any]:
    """Inspect local files/config only; this intentionally never probes SaaS."""
    profile = load_mvp_profile(PROFILE_PATH)
    runtime = mvp_readiness_report(environ=environ, profile=profile)
    missing_files = [path for path in REQUIRED_FILES if not (ROOT / path).is_file()]
    schema_path = ROOT / "deploy/supabase/schema.sql"
    schema = schema_path.read_text(encoding="utf-8") if schema_path.is_file() else ""
    schema_tables = [name for name in ("workspaces", "canonical_events", "public_signals", "artifacts", "run_envelopes", "source_readiness") if f"public.{name}" in schema]
    required_indexes = [name for name in ("event_type", "aggregate", "workspace_occurred", "correlation") if name in schema]
    status = "blocked" if runtime["unsafe_live_flags"] or missing_files else runtime["status"]
    return {
        "profile_path": str(PROFILE_PATH.relative_to(ROOT)).replace("\\", "/"),
        "profile_version": profile.get("profile_version"),
        "status": status,
        "files_present": not missing_files,
        "missing_files": missing_files,
        "supabase_schema_tables": schema_tables,
        "supabase_required_indexes": required_indexes,
        "frontend_present": (ROOT / "frontend/package.json").is_file(),
        "api_present": (ROOT / "backend/api.py").is_file(),
        "runtime": runtime,
        "deployment_targets": profile.get("deployment_targets", []),
        "health_endpoints": profile.get("health_endpoints", []),
        "network_calls": False,
        "mutated": False,
        "next_actions": _next_actions(status, runtime, missing_files),
    }


def _next_actions(status: str, runtime: dict[str, Any], missing_files: list[str]) -> list[str]:
    actions: list[str] = []
    if missing_files:
        actions.append("restore committed MVP deployment files")
    if runtime["unsafe_live_flags"]:
        actions.append("disable reported live-commerce flags before deployment")
    if runtime["missing_required_env"]:
        actions.append("set required MVP environment variables with safe values")
    if not runtime["supabase_configured"]:
        actions.append("Supabase is optional: use JSONL first or configure a server-only staging project")
    if status == "ready":
        actions.append("deploy frontend/API independently and manually verify /health and /ready")
    return actions


def markdown_report(report: dict[str, Any]) -> str:
    runtime = report["runtime"]
    lines = ["# MarketOS MVP Island readiness", "", f"- Status: **{report['status']}**", f"- Profile: `{report['profile_path']}`", f"- Network calls: `{report['network_calls']}`", "", "## Configuration", "", f"- Missing required env: {', '.join(runtime['missing_required_env']) or 'none'}", f"- Unsafe live flags: {', '.join(runtime['unsafe_live_flags']) or 'none'}", f"- Supabase configured: `{runtime['supabase_configured']}`", f"- Schema tables: {', '.join(report['supabase_schema_tables']) or 'missing'}", "", "## Next actions", ""]
    lines.extend(f"- {action}" for action in report["next_actions"] or ["No action required by this local check."])
    lines.append("\nThis report is local/read-only and did not contact a provider or enable a capability.")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true", help="emit JSON (default)")
    output.add_argument("--markdown", action="store_true", help="emit Markdown")
    parser.add_argument("--output", help="optional report output path under artifacts/")
    args = parser.parse_args(argv)
    report = build_mvp_readiness(dict(os.environ))
    rendered = markdown_report(report) if args.markdown else json.dumps(report, sort_keys=True, indent=2) + "\n"
    if args.output:
        target = (ROOT / args.output).resolve()
        artifacts = (ROOT / "artifacts").resolve()
        if target != artifacts and artifacts not in target.parents:
            parser.error("--output must stay under artifacts/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
