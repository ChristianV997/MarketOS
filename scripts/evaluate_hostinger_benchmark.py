"""Opt-in runtime benchmark for the Hostinger HostingProvider adapter.

Benchmarks `backend.integrations.hostinger.HostingerHostingAdapter` against
whatever real `HOSTINGER_API_TOKEN` is configured. Fully read-only by
construction — `HostingProvider` has no mutating methods at all (MarketOS
does not provision or de-provision hosting infrastructure); this probes
`health()`, `get_status()`, `list_sites()`, and `get_plan_usage()`. See
scripts/_provider_benchmark.py for the shared harness.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from scripts._provider_benchmark import cli_main, run_adapter_benchmark
except ModuleNotFoundError:  # direct ``python scripts/evaluate_hostinger_benchmark.py``
    from _provider_benchmark import cli_main, run_adapter_benchmark


def benchmark(execute: bool) -> dict[str, object]:
    from backend.integrations.hostinger import HostingerHostingAdapter

    return run_adapter_benchmark(
        candidate="hostinger",
        reviewed_ref="n/a (proprietary SaaS API)",
        make_adapter=HostingerHostingAdapter,
        read_probes={
            "get_status": lambda a: a.get_status(),
            "list_sites": lambda a: a.list_sites(),
            "get_plan_usage": lambda a: a.get_plan_usage(),
        },
        execute=execute,
    )


def main() -> int:
    return cli_main(benchmark)


if __name__ == "__main__":
    raise SystemExit(main())
