"""Prometheus metrics for market-research source ingestion."""
from __future__ import annotations

try:
    from prometheus_client import Counter, Histogram

    _fetches = Counter("marketos_research_source_fetch_total", "Research source fetches", ["source", "status"])
    _records = Counter("marketos_research_source_records_total", "Research source records", ["source", "kind"])
    _retries = Counter("marketos_research_source_retries_total", "Research source retries", ["source"])
    _duration = Histogram("marketos_research_source_duration_seconds", "Research source duration", ["source"])
except ImportError:  # pragma: no cover
    _fetches = _records = _retries = _duration = None


def record_fetch(source: str, status: str, duration_seconds: float = 0.0) -> None:
    if _fetches is not None:
        _fetches.labels(source=source, status=status).inc()
        _duration.labels(source=source).observe(max(0.0, duration_seconds))


def record_records(source: str, *, fetched: int = 0, persisted: int = 0, rejected: int = 0) -> None:
    if _records is not None:
        _records.labels(source=source, kind="fetched").inc(max(0, fetched))
        _records.labels(source=source, kind="persisted").inc(max(0, persisted))
        _records.labels(source=source, kind="rejected").inc(max(0, rejected))


def record_retry(source: str) -> None:
    if _retries is not None:
        _retries.labels(source=source).inc()
