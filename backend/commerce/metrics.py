"""Prometheus metrics for the canonical commerce execution loop.

Labels are intentionally bounded to phase/status/provider-style values. Product,
campaign, URL, and user-content identifiers must never become metric labels.
"""
from __future__ import annotations

from backend.observability.metrics import _counter, _histogram


cycles_total = _counter("commerce_cycles_total", "Commerce cycles by outcome", ["status", "dry_run"])
phase_duration_seconds = _histogram(
    "commerce_phase_duration_seconds",
    "Commerce phase duration in seconds",
    ["phase"],
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1, 5, 15, 60],
)
launches_total = _counter("commerce_launches_total", "Commerce launch attempts by outcome", ["status", "dry_run"])
feedback_total = _counter("commerce_feedback_total", "Commerce feedback records by outcome", ["status"])
idempotency_skips_total = _counter("commerce_idempotency_skips_total", "Commerce operations skipped due to existing state")


__all__ = [
    "cycles_total",
    "phase_duration_seconds",
    "launches_total",
    "feedback_total",
    "idempotency_skips_total",
]
