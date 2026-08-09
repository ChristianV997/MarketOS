"""Opt-in runtime benchmark for the Stripe MX PaymentProvider adapter.

Benchmarks `backend.integrations.stripe_mx.StripeMxPaymentAdapter` against
whatever real `STRIPE_SECRET_KEY` is configured (reused from the existing
`stripe` credential key). Read-only: only calls `health()` and
`list_payments(limit=5)`; never estimates a live charge or handles a
webhook mutation. See scripts/_provider_benchmark.py for the shared harness.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from scripts._provider_benchmark import cli_main, run_adapter_benchmark
except ModuleNotFoundError:  # direct ``python scripts/evaluate_stripe_mx_benchmark.py``
    from _provider_benchmark import cli_main, run_adapter_benchmark


def benchmark(execute: bool) -> dict[str, object]:
    from backend.integrations.stripe_mx import StripeMxPaymentAdapter

    return run_adapter_benchmark(
        candidate="stripe_mx",
        reviewed_ref="n/a (proprietary SaaS API)",
        make_adapter=StripeMxPaymentAdapter,
        read_probes={"list_payments": lambda a: a.list_payments(limit=5)},
        execute=execute,
    )


def main() -> int:
    return cli_main(benchmark)


if __name__ == "__main__":
    raise SystemExit(main())
