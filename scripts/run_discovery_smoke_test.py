#!/usr/bin/env python3
"""Discovery pipeline smoke test.

Runs every registered discovery adapter (Amazon, MercadoLibre, Reddit,
Google Trends, YouTube, TikTok organic, Alibaba) via core.signals.SignalEngine,
then reports which sources returned real vs mock data right now — with zero
API keys required for the real ones (Reddit, MercadoLibre, Google Trends,
YouTube).

Usage:
    python scripts/run_discovery_smoke_test.py [--json]
"""
import sys
import json as json_lib
from datetime import datetime, timezone

sys.path.insert(0, "/home/user/my_OS")


def main() -> int:
    json_output = "--json" in sys.argv

    from core.signals import signal_engine
    from backend.discovery.registry import discovery_registry

    signals = signal_engine.get()
    report = discovery_registry.status_report()
    top = signal_engine.top_opportunities(signals, n=5)

    if json_output:
        print(json_lib.dumps({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_signals": len(signals),
            "sources": report,
            "top_opportunities": top,
        }, indent=2, default=str))
        return 0

    now = datetime.now(timezone.utc).isoformat()
    print()
    print(f"MarketOS Discovery Smoke Test — {now}")
    print("=" * 76)
    print(f"{'Source':<20}{'Status':<16}{'Signals':<10}{'Credential Needed'}")
    print("-" * 76)

    live_count = 0
    for s in report:
        status = s["status"]
        if status == "live":
            live_count += 1
        creds = ", ".join(s["credential_env_vars"]) if s["credential_env_vars"] else "none"
        count = s["last_fetch_count"] if s["last_fetch_count"] is not None else "-"
        print(f"{s['name']:<20}{status:<16}{str(count):<10}{creds}")

    print("-" * 76)
    total_sources = len(report)
    print(f"Total signals: {len(signals)}   |   "
          f"Real/live sources: {live_count}/{total_sources}   |   "
          f"Mock sources: {total_sources - live_count}/{total_sources}")

    if live_count == 0:
        print()
        print("⚠️  WARNING: zero sources are live — you're seeing 100% mock data")
        print("   right now. Check network access if this is unexpected.")

    print()
    print("Top 5 opportunities (by score):")
    for i, opp in enumerate(top, start=1):
        product = str(opp.get("product", ""))[:50]
        score = opp.get("score", 0.0)
        source = opp.get("source", "unknown")
        market = opp.get("market", opp.get("platform", ""))
        print(f"  {i}. {product:<52} score={score:<6} source={source:<14} market={market}")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
