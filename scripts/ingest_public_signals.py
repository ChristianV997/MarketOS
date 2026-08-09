"""Manually ingest advisory public RSS signals; network access is explicit."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.events.repository import JsonlEventRepository
from backend.signals.public_signal_cache import PublicSignalCache
from backend.signals.public_signal_policy import validate_public_ingestion_request
from backend.signals.public_signal_reporting import build_public_signal_audit
from backend.signals.public_sources import (
    RSS_SOURCE,
    append_public_signal_events,
    ingest_public_rss,
    public_rss_readiness,
)

FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "public_signals"


def _markdown(report: dict) -> str:
    rows = ["# Public Signal Ingestion", "", "Signals are advisory public observations, not demand, profitability, ROAS, conversion, or launch evidence.", "",
            f"- Source: `{report['source']}`", f"- Status: **{report['status']}**", f"- Signals: {len(report['signals'])}",
            f"- Cache: {report['cache_status']}", f"- Network used: {report['network_used']}", "", "## Signals", ""]
    rows.extend(f"- {item['rank']}. {item['title']} — {item['evidence_url']}" for item in report["signals"])
    rows.extend(["", "No launch, spend, publishing, provider mutation, or credentialed action is authorized.", ""])
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="rss", choices=["rss"])
    parser.add_argument("--query", default="ecommerce trends")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--workspace-id", default="public-signal-dry-run")
    parser.add_argument("--write-jsonl")
    parser.add_argument("--cache-dir", default=str(ROOT / "artifacts" / "public-signal-cache"))
    parser.add_argument("--fixtures", action="store_true")
    parser.add_argument("--allow-network", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true")
    mode.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)
    guard = validate_public_ingestion_request("rss", args.query, args.limit, allow_network=args.allow_network, fixture_mode=args.fixtures)
    if not guard.allowed:
        report = {"source": RSS_SOURCE, "status": "blocked", "errors": guard.reasons, "network_used": False, "signals": [], "guard": guard.to_dict(), "written_event_ids": []}
        print(json.dumps(report, sort_keys=True, indent=2) + "\n")
        return 0
    cache = PublicSignalCache(args.cache_dir)
    fixture = (FIXTURE_ROOT / "rss_sample.xml").read_text(encoding="utf-8") if args.fixtures else None
    result = ingest_public_rss(args.query, limit=args.limit, allow_network=args.allow_network, cache=cache, fixture_xml=fixture)
    report = result.to_dict()
    report["guard"] = guard.to_dict()
    report["readiness"] = public_rss_readiness(cache, args.query)
    report["written_event_ids"] = []
    if args.write_jsonl and result.signals:
        repository = JsonlEventRepository(args.write_jsonl)
        report["written_event_ids"] = append_public_signal_events(result.signals, repository, workspace_id=args.workspace_id, cache_status=result.cache_status)
    report["audit"] = build_public_signal_audit(result, workspace_id=args.workspace_id).to_dict()
    content = _markdown(report) if args.markdown else json.dumps(report, sort_keys=True, indent=2) + "\n"
    print(content, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
