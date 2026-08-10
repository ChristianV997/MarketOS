"""Run a local, credential-free Phase 1 MVP smoke through dashboard-readable events."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.ecommerce.shopify_readonly.events import shopify_batch_events
from backend.ecommerce.shopify_readonly.importer import import_shopify_readonly
from backend.events.query_models import EventQuery
from backend.events.query_service import build_event_timeline, load_events_from_jsonl
from backend.events.repository import JsonlEventRepository
from backend.mvp_commerce.events import commerce_mvp_events
from backend.mvp_commerce.public_run import run_commerce_mvp_from_public_rss
from backend.mvp_commerce.runner import run_commerce_mvp_slice

try:
    from .deployment_smoke_check import build_report
except ImportError:  # Direct ``python scripts/local_mvp_smoke.py`` execution.
    from deployment_smoke_check import build_report

FIXTURE = ROOT / "tests/fixtures/commerce_mvp/public_signals.json"
SHOPIFY_FIXTURE = ROOT / "tests/fixtures/shopify_readonly/shopify_sample.json"
ARTIFACTS = (ROOT / "artifacts").resolve()


def _summary(status: str, *, events: list[Any], timeline: dict[str, Any] | None = None, warnings: list[str] | None = None) -> dict[str, Any]:
    types: dict[str, int] = {}
    for event in events:
        types[event.event_type] = types.get(event.event_type, 0) + 1
    required = {"commerce_mvp_run_started", "commerce_mvp_signal_batch_selected", "commerce_mvp_run_completed"}
    return {
        "status": status,
        "event_count": len(events),
        "event_type_counts": dict(sorted(types.items())),
        "required_event_types_present": sorted(required.intersection(types)),
        "all_events_non_authoritative": all(event.metadata.get("non_authoritative") is True for event in events),
        "timeline_event_count": len(timeline.get("events", [])) if timeline else len(events),
        "warnings": warnings or [],
    }


def run_smoke(*, query: str, allow_public_network: bool, include_shopify_fixture: bool, write_jsonl: str | None, skip_frontend_build: bool) -> dict[str, Any]:
    deployment = build_report(environ=dict(os.environ))
    context = None
    batch = None
    if include_shopify_fixture:
        batch, context = import_shopify_readonly(SHOPIFY_FIXTURE, "local-mvp-smoke")
    if allow_public_network:
        result = run_commerce_mvp_from_public_rss(
            workspace_id="local-mvp-smoke",
            query=query,
            allow_network=True,
            cache_dir=os.getenv("MARKETOS_PUBLIC_SIGNAL_CACHE_DIR", str(ROOT / "artifacts/public-signal-cache")),
            shopify_store_context=context,
        )
        events = list(result.events)
        status = result.status
        warnings = list(result.ingestion.warnings) + list(result.ingestion.errors)
    else:
        run = run_commerce_mvp_slice(workspace_id="local-mvp-smoke", query=query, signal_fixture_path=FIXTURE, shopify_store_context=context)
        events = commerce_mvp_events(run)
        status = "fixture"
        warnings = list(run.warnings)
    if batch is not None:
        events = shopify_batch_events(batch, context) + events
    if write_jsonl:
        target = (ROOT / write_jsonl).resolve()
        if ARTIFACTS not in target.parents:
            raise ValueError("--write-jsonl must stay under artifacts/")
        JsonlEventRepository(target).append_many(events)
        loaded, load_warnings = load_events_from_jsonl(target)
        timeline = build_event_timeline(loaded, EventQuery(limit=250), warnings=load_warnings).to_dict()
    else:
        timeline = build_event_timeline(events, EventQuery(limit=250)).to_dict()
    frontend = {"status": "skipped" if skip_frontend_build else "not_run"}
    if not skip_frontend_build:
        completed = subprocess.run(["npm", "run", "build"], cwd=ROOT / "frontend", capture_output=True, text=True, timeout=180, check=False)
        frontend = {"status": "passed" if completed.returncode == 0 else "failed"}
    return {
        "deployment_contract": deployment,
        "run": _summary(status, events=events, timeline=timeline, warnings=warnings),
        "timeline": {"event_count": len(timeline.get("events", [])), "event_type_counts": timeline.get("event_type_counts", {}), "warnings": timeline.get("warnings", [])},
        "frontend_build": frontend,
        "dashboard_route": "/operator/events",
        "read_only": True,
        "mutated": False,
        "network_used": allow_public_network,
        "next_actions": ["Deploy FastAPI to Railway and frontend to Vercel after env review.", "Probe /health, /ready, /api/events/readiness, and /operator/events.", "Keep public and Supabase gates off until explicitly approved."],
    }


def markdown_report(report: dict[str, Any]) -> str:
    run = report["run"]
    lines = ["# Local MarketOS MVP smoke", "", f"- Run status: **{run['status']}**", f"- Events: `{run['event_count']}`", f"- Dashboard: `{report['dashboard_route']}`", f"- Frontend build: `{report['frontend_build']['status']}`", f"- Network used: `{report['network_used']}`", f"- Mutated: `{report['mutated']}`", "", "## Next actions", ""]
    lines.extend(f"- {item}" for item in report["next_actions"])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-public-network", action="store_true")
    parser.add_argument("--query", default="portable espresso maker")
    parser.add_argument("--include-shopify-fixture", action="store_true")
    parser.add_argument("--write-jsonl")
    parser.add_argument("--skip-frontend-build", action="store_true")
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true")
    output.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)
    report = run_smoke(query=args.query, allow_public_network=args.allow_public_network, include_shopify_fixture=args.include_shopify_fixture, write_jsonl=args.write_jsonl, skip_frontend_build=args.skip_frontend_build)
    print(markdown_report(report) if args.markdown else json.dumps(report, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__": raise SystemExit(main())
