"""Tests for scripts._provider_benchmark.run_adapter_benchmark — the shared
opt-in runtime-benchmark harness backing every evaluate_<provider>_benchmark.py
script. Uses fake adapters (no real network) to exercise every branch."""
from __future__ import annotations

from backend.contracts.adapters import AdapterHealth
from scripts._provider_benchmark import run_adapter_benchmark


class _FakeAdapter:
    def __init__(self, *, configured: bool, reachable: bool, capabilities=()):
        self._configured = configured
        self._reachable = reachable
        self._capabilities = capabilities

    def health(self):
        return AdapterHealth(
            "fake", configured=self._configured, reachable=self._reachable,
            capabilities=self._capabilities, detail="" if self._reachable else "boom",
        )


def test_default_is_planned_and_never_constructs_adapter():
    calls = []
    run_adapter_benchmark(
        candidate="fake", reviewed_ref="v1", make_adapter=lambda: calls.append(1) or _FakeAdapter(configured=True, reachable=True),
        execute=False,
    )
    assert calls == []


def test_unconfigured_adapter_reports_unconfigured():
    report = run_adapter_benchmark(
        candidate="fake", reviewed_ref="v1",
        make_adapter=lambda: _FakeAdapter(configured=False, reachable=False),
        execute=True,
    )
    assert report["status"] == "unconfigured"
    assert report["executed"] is False


def test_unreachable_configured_adapter_reports_unreachable():
    report = run_adapter_benchmark(
        candidate="fake", reviewed_ref="v1",
        make_adapter=lambda: _FakeAdapter(configured=True, reachable=False),
        execute=True,
    )
    assert report["status"] == "unreachable"
    assert len(report["health_latency_ms"]) == 3


def test_reachable_adapter_with_passing_probes():
    report = run_adapter_benchmark(
        candidate="fake", reviewed_ref="v1",
        make_adapter=lambda: _FakeAdapter(configured=True, reachable=True),
        read_probes={"list_things": lambda a: [{"id": 1}, {"id": 2}]},
        execute=True,
    )
    assert report["status"] == "passed"
    assert report["probe_results"]["list_things"]["sample"] == [{"id": 1}, {"id": 2}]
    assert report["probe_errors"] == {}


def test_probe_error_reports_partial_not_a_raise():
    def _boom(_adapter):
        raise RuntimeError("network down")

    report = run_adapter_benchmark(
        candidate="fake", reviewed_ref="v1",
        make_adapter=lambda: _FakeAdapter(configured=True, reachable=True),
        read_probes={"broken": _boom},
        execute=True,
    )
    assert report["status"] == "partial"
    assert "network down" in report["probe_errors"]["broken"]


def test_mutating_operations_flag_is_always_false():
    report = run_adapter_benchmark(candidate="fake", reviewed_ref="v1", make_adapter=lambda: None)
    assert report["mutating_operations"] is False
