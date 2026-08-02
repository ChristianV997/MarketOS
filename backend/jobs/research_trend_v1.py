import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

from backend.adapters.research import AdapterFetchError, GoogleTrendsAdapterV1, ResearchAdapterRegistry
from backend.jobs.runner import JobRegistry
from backend.research import TrendRecordStore

logger = logging.getLogger(__name__)


class AdapterMetrics:
    def __init__(self):
        self.counters = {
            "adapter_fetch_total": 0,
            "adapter_fetch_errors_total": 0,
            "adapter_records_fetched": 0,
            "adapter_records_rejected": 0,
        }
        self.by_source: dict[str, dict[str, int]] = {}

    def _source(self, source: str) -> dict[str, int]:
        return self.by_source.setdefault(source, {
            "fetches": 0,
            "errors": 0,
            "records_fetched": 0,
            "records_persisted": 0,
            "records_rejected": 0,
        })

    def record_fetch(self, count: int, *, source: str = "unknown", persisted: int | None = None, rejected: int = 0):
        self.counters["adapter_fetch_total"] += 1
        self.counters["adapter_records_fetched"] += count
        self.counters["adapter_records_rejected"] += rejected
        item = self._source(source)
        item["fetches"] += 1
        item["records_fetched"] += count
        item["records_persisted"] += count if persisted is None else persisted
        item["records_rejected"] += rejected

    def record_error(self, *, source: str = "unknown"):
        self.counters["adapter_fetch_errors_total"] += 1
        self._source(source)["errors"] += 1

    @property
    def snapshot(self) -> dict[str, Any]:
        return {**self.counters, "by_source": {key: dict(value) for key, value in self.by_source.items()}}


def _source_enabled() -> bool:
    return str(os.getenv("FF_PILLAR_A_SOURCE_V1", "false")).strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def build_default_adapter_registry() -> ResearchAdapterRegistry:
    registry = ResearchAdapterRegistry()
    registry.register(
        GoogleTrendsAdapterV1.name,
        GoogleTrendsAdapterV1(
            max_pages=_int_env("PILLAR_A_SOURCE_V1_MAX_PAGES", 1),
            geo=os.getenv("PILLAR_A_SOURCE_V1_GEO", "US"),
            language=os.getenv("PILLAR_A_SOURCE_V1_LANG", "en-US"),
            timeout_seconds=_int_env("PILLAR_A_SOURCE_V1_TIMEOUT_SECONDS", 15),
            velocity_baseline=_float_env("PILLAR_A_SOURCE_V1_VELOCITY_BASELINE", 1000.0),
            confidence_baseline=_float_env("PILLAR_A_SOURCE_V1_CONFIDENCE_BASELINE", 0.7),
        ),
    )
    return registry


def _canonicalize_and_persist(
    adapter: Any,
    *,
    store: TrendRecordStore,
    fetched_at: datetime,
    metrics: AdapterMetrics,
) -> dict[str, int]:
    """Persist valid records while isolating malformed records in one batch."""
    raw_records = adapter.fetch()
    normalized: list[dict[str, Any]] = []
    rejected = 0
    for raw_record in raw_records:
        try:
            normalized.append(adapter.to_canonical(raw_record, fetched_at=fetched_at))
        except Exception as err:
            rejected += 1
            logger.warning(
                "research_record_rejected source=%s error=%s",
                adapter.name,
                err,
            )
    persisted = store.append_many(normalized)
    metrics.record_fetch(
        len(raw_records),
        source=adapter.name,
        persisted=persisted,
        rejected=rejected + len(normalized) - persisted,
    )
    return {"fetched": len(raw_records), "persisted": persisted, "rejected": rejected + len(normalized) - persisted}


def register_research_trend_v1_job(
    job_registry: JobRegistry,
    *,
    adapter_registry: ResearchAdapterRegistry | None = None,
    store: TrendRecordStore | None = None,
    metrics: AdapterMetrics | None = None,
) -> None:
    adapters = adapter_registry or build_default_adapter_registry()
    record_store = store or TrendRecordStore()
    fetch_metrics = metrics or AdapterMetrics()
    adapter_name = GoogleTrendsAdapterV1.name

    def run_job() -> dict[str, Any]:
        if not _source_enabled():
            logger.info(
                {
                    "job": "research.trend.v1",
                    "adapter": adapter_name,
                    "status": "skipped",
                    "reason": "feature_flag_disabled",
                }
            )
            return {"status": "skipped", "records": 0}

        started = time.perf_counter()
        fetched_at = datetime.now(timezone.utc)

        try:
            adapter = adapters.get(adapter_name)
            stats = _canonicalize_and_persist(adapter, store=record_store, fetched_at=fetched_at, metrics=fetch_metrics)
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.info(
                {
                    "job": "research.trend.v1",
                    "adapter": adapter_name,
                    "status": "succeeded",
                    "record_count": stats["persisted"],
                    "rejected_count": stats["rejected"],
                    "duration_ms": duration_ms,
                }
            )
            return {"status": "succeeded", "records": stats["persisted"], "rejected": stats["rejected"]}
        except AdapterFetchError as err:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            fetch_metrics.record_error(source=adapter_name)
            logger.error(
                {
                    "job": "research.trend.v1",
                    "adapter": adapter_name,
                    "status": "failed",
                    "duration_ms": duration_ms,
                    "error_type": err.error_type,
                    "error": str(err),
                    "context": err.context,
                }
            )
            raise

    job_registry.register("research.trend.v1", run_job)


def register_research_sources_job(
    job_registry: JobRegistry,
    *,
    adapter_registry: ResearchAdapterRegistry | None = None,
    store: TrendRecordStore | None = None,
    metrics: AdapterMetrics | None = None,
) -> None:
    """Register a fault-isolated fan-out job for every configured source."""
    adapters = adapter_registry or build_default_adapter_registry()
    record_store = store or TrendRecordStore()
    fetch_metrics = metrics or AdapterMetrics()

    def run_job() -> dict[str, Any]:
        if not _source_enabled():
            return {"status": "skipped", "sources": {}, "metrics": fetch_metrics.snapshot}

        started = time.perf_counter()
        fetched_at = datetime.now(timezone.utc)
        sources: dict[str, Any] = {}
        for name, adapter in sorted(adapters.all().items()):
            try:
                stats = _canonicalize_and_persist(
                    adapter,
                    store=record_store,
                    fetched_at=fetched_at,
                    metrics=fetch_metrics,
                )
                sources[name] = {"status": "succeeded", **stats}
            except Exception as err:
                fetch_metrics.record_error(source=name)
                sources[name] = {"status": "failed", "error": str(err)}
                logger.exception("research_source_failed source=%s", name)

        succeeded = sum(item["status"] == "succeeded" for item in sources.values())
        failed = sum(item["status"] == "failed" for item in sources.values())
        status = "succeeded" if failed == 0 else ("partial" if succeeded else "failed")
        result = {
            "status": status,
            "sources": sources,
            "metrics": fetch_metrics.snapshot,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }
        if status == "failed":
            raise RuntimeError("all configured research sources failed")
        return result

    job_registry.register("research.sources.v1", run_job)


def register_research_prune_job(job_registry: JobRegistry, *, store: TrendRecordStore | None = None) -> None:
    record_store = store or TrendRecordStore()

    def run_job() -> dict[str, Any]:
        deleted = record_store.pruneOldRecords()
        logger.info({"job": "research.prune", "status": "succeeded", "deleted_records": deleted})
        return {"status": "succeeded", "deleted_records": deleted}

    job_registry.register("research.prune", run_job)
