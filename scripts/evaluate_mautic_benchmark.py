"""Opt-in runtime benchmark for the Mautic MarketingAutomationProvider adapter.

Benchmarks `backend.integrations.mautic.MauticMarketingAutomationAdapter`
against whatever real `MAUTIC_BASE_URL`/`MAUTIC_USERNAME`/`MAUTIC_PASSWORD`
are configured. Read-only: only calls `health()` (which itself only reads
`GET /contacts?limit=1`) — every other adapter method upserts a contact,
segment, campaign, or email event, so there is no additional read-only
listing method to probe here. See scripts/_provider_benchmark.py for the
shared harness.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from scripts._provider_benchmark import cli_main, run_adapter_benchmark
except ModuleNotFoundError:  # direct ``python scripts/evaluate_mautic_benchmark.py``
    from _provider_benchmark import cli_main, run_adapter_benchmark


def benchmark(execute: bool) -> dict[str, object]:
    from backend.integrations.mautic import MauticMarketingAutomationAdapter

    return run_adapter_benchmark(
        candidate="mautic",
        reviewed_ref="pending-deferred-review",
        make_adapter=MauticMarketingAutomationAdapter,
        execute=execute,
    )


def main() -> int:
    return cli_main(benchmark)


if __name__ == "__main__":
    raise SystemExit(main())
