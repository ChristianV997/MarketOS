"""Opt-in runtime benchmark for the PostHog backend AnalyticsProvider adapter.

Benchmarks `backend.integrations.posthog_backend.PostHogAnalyticsAdapter`
against whatever real `POSTHOG_PROJECT_API_KEY`/`POSTHOG_PERSONAL_API_KEY`
are configured. Read-only: only calls `health()` and
`query_events(event_name="service_run", limit=5)` — never calls
`capture_event`, which would write a real analytics event. Distinct from
the existing frontend-only posthog-js client
(frontend/src/lib/posthog.ts). See scripts/_provider_benchmark.py for the
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
except ModuleNotFoundError:  # direct ``python scripts/evaluate_posthog_backend_benchmark.py``
    from _provider_benchmark import cli_main, run_adapter_benchmark


def benchmark(execute: bool) -> dict[str, object]:
    from backend.integrations.posthog_backend import PostHogAnalyticsAdapter

    return run_adapter_benchmark(
        candidate="posthog_backend",
        reviewed_ref="posthog-js@1.x",
        make_adapter=PostHogAnalyticsAdapter,
        read_probes={"query_events": lambda a: a.query_events(event_name="service_run", limit=5)},
        execute=execute,
    )


def main() -> int:
    return cli_main(benchmark)


if __name__ == "__main__":
    raise SystemExit(main())
