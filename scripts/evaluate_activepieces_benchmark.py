"""Opt-in runtime benchmark for the Activepieces CustomerAutomationProvider adapter.

Benchmarks `backend.integrations.activepieces.ActivepiecesAutomationAdapter`
against whatever real `ACTIVEPIECES_BASE_URL`/`ACTIVEPIECES_API_KEY` are
configured. Read-only: only calls `health()` and
`list_available_workflows()`; never triggers a workflow. See
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
except ModuleNotFoundError:  # direct ``python scripts/evaluate_activepieces_benchmark.py``
    from _provider_benchmark import cli_main, run_adapter_benchmark


def benchmark(execute: bool) -> dict[str, object]:
    from backend.integrations.activepieces import ActivepiecesAutomationAdapter

    return run_adapter_benchmark(
        candidate="activepieces",
        reviewed_ref="pending-deferred-review",
        make_adapter=ActivepiecesAutomationAdapter,
        read_probes={"list_available_workflows": lambda a: a.list_available_workflows()},
        execute=execute,
    )


def main() -> int:
    return cli_main(benchmark)


if __name__ == "__main__":
    raise SystemExit(main())
