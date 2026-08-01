"""Shared opt-in runtime-benchmark harness for MarketOS's own commerce/
payment/CRM-adjacent adapters (backend/integrations/*).

Unlike scripts/evaluate_medusa_sidecar.py and scripts/evaluate_saleor_benchmark.py
(which spin up a Docker sidecar this repo doesn't otherwise run), these
adapters are either pure SaaS APIs (Stripe MX, Mercado Pago MX, PostHog) or
externally operated services an operator brings themselves (WooCommerce,
Chatwoot, Mautic, Activepieces, Hostinger) — there is nothing for MarketOS
to start or tear down. This harness instead benchmarks latency/reachability
against whatever real credentials the operator has already configured, by
calling the adapter's own existing read-only methods
(``health()`` plus, where one exists, a `list_*`/`get_*`/`query_*` read
method) — no new HTTP/GraphQL code is written per provider, so there is
still exactly one code path for "is this integration reachable"
(``backend.contracts.adapters.AdapterHealth``) and one for "how fast is it"
(this module).

Every probe is read-only by construction — the mutating methods on each
Protocol (``create_*``, ``upsert_*``, ``trigger_*``, ``handle_webhook``,
``capture_event``, ...) are never called here. Default is always
non-executing: pass ``--execute`` to make any real network call. No
credentials are read, stored, or printed by this module — that remains
each adapter's own job (see backend/config.py).
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).parents[1]

_TERMINAL_STATUSES = {"planned", "passed", "partial", "unconfigured", "unreachable"}


def _safe_sample(result: Any) -> Any:
    """Truncate a probe's result to something small and JSON-safe for the report."""
    if isinstance(result, (list, tuple)):
        return [_safe_sample(item) for item in list(result)[:2]]
    if isinstance(result, dict):
        return {k: _safe_sample(result[k]) for k in list(result)[:5]}
    return result


def run_adapter_benchmark(
    *,
    candidate: str,
    reviewed_ref: str,
    make_adapter: Callable[[], Any],
    read_probes: dict[str, Callable[[Any], Any]] | None = None,
    execute: bool = False,
    samples: int = 3,
) -> dict[str, object]:
    """Benchmark ``health()`` + any read-only probes for one MarketOS adapter.

    Never mutates anything. ``execute=False`` (the default) reports the plan
    without constructing the adapter or importing its optional HTTP client.
    Never raises: an unconfigured adapter, an unreachable one, or a probe
    that errors all degrade to a structured, honest report status rather
    than propagating an exception.
    """
    read_probes = read_probes or {}
    report: dict[str, object] = {
        "candidate": candidate,
        "reviewed_ref": reviewed_ref,
        "mutating_operations": False,
        "executed": False,
        "read_probes": sorted(read_probes.keys()),
    }
    if not execute:
        report.update(status="planned", reason="pass --execute to probe the configured adapter (reads only, no mutation)")
        return report

    adapter = make_adapter()
    health = adapter.health()
    report["configured"] = health.configured
    report["capabilities"] = list(health.capabilities)
    if not health.configured:
        report.update(
            status="unconfigured",
            reason=health.detail or "no credentials configured — benchmark requires real credentials",
        )
        return report

    health_latencies: list[float] = []
    for _ in range(max(1, samples)):
        started = time.perf_counter()
        health = adapter.health()
        health_latencies.append(round((time.perf_counter() - started) * 1000, 3))
    report["health_latency_ms"] = health_latencies
    report["health_latency_p95_ms"] = max(health_latencies)
    if not health.reachable:
        report.update(status="unreachable", reason=health.detail or "health() reported unreachable")
        return report

    probe_results: dict[str, Any] = {}
    probe_errors: dict[str, str] = {}
    for name, probe in read_probes.items():
        try:
            started = time.perf_counter()
            result = probe(adapter)
            probe_results[name] = {
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                "sample": _safe_sample(result),
            }
        except Exception as exc:  # noqa: BLE001 — the benchmark reports failures, never raises
            probe_errors[name] = str(exc)

    report.update(
        status="passed" if not probe_errors else "partial",
        executed=True,
        probe_results=probe_results,
        probe_errors=probe_errors,
    )
    return report


def cli_main(benchmark_fn: Callable[[bool], dict[str, object]]) -> int:
    """Standard CLI wrapper every evaluate_<provider>_benchmark.py uses."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="probe the configured adapter (reads only, no mutation)")
    parser.add_argument("--output", type=Path, help="write JSON report to this path")
    args = parser.parse_args()
    report = benchmark_fn(args.execute)
    payload = json.dumps(report, indent=2, sort_keys=True, default=str) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0 if report.get("status") in _TERMINAL_STATUSES else 1
