"""Opt-in runtime benchmark for the WooCommerce CommerceProvider adapter.

Benchmarks `backend.integrations.woocommerce.WooCommerceCommerceAdapter`
against whatever real, operator-configured WooCommerce store credentials
are present (`WOOCOMMERCE_STORE_URL`/`WOOCOMMERCE_CONSUMER_KEY`/
`WOOCOMMERCE_CONSUMER_SECRET` — see .env.example). Read-only: only calls
`health()` and `list_products(limit=5)`; never creates a cart, order,
fulfillment, or refund. See scripts/_provider_benchmark.py for the shared
harness this composes rather than duplicates.

WooCommerce is `legal_review_required` in docs/oss/LICENSE_MANIFEST.yml
(GPL-3.0) — this script does not vendor or import any WooCommerce source,
it only calls the existing adapter's independent REST API client.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from scripts._provider_benchmark import cli_main, run_adapter_benchmark
except ModuleNotFoundError:  # direct ``python scripts/evaluate_woocommerce_benchmark.py``
    from _provider_benchmark import cli_main, run_adapter_benchmark


def benchmark(execute: bool) -> dict[str, object]:
    from backend.integrations.woocommerce import WooCommerceCommerceAdapter

    return run_adapter_benchmark(
        candidate="woocommerce",
        reviewed_ref="pending-version-pin",
        make_adapter=WooCommerceCommerceAdapter,
        read_probes={"list_products": lambda a: a.list_products(limit=5)},
        execute=execute,
    )


def main() -> int:
    return cli_main(benchmark)


if __name__ == "__main__":
    raise SystemExit(main())
