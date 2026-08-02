import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

from backend.adapters.research import (
    AdapterFetchError,
    AmazonBestsellersResearchAdapter,
    GoogleTrendsAdapterV1,
    MercadoLibreResearchAdapter,
    RedditResearchAdapter,
    ResearchAdapterRegistry,
    TikTokOrganicResearchAdapter,
    YouTubeResearchAdapter,
)
from backend.jobs.runner import JobRegistry
from backend.research import IngestionRunStore, TrendRecordStore
from backend.research import metrics as research_metrics

logger = logging.getLogger(__name__)


class AdapterMetrics:
    def __init__(self):
        self.counters = {
            "adapter_fetch_total": 0,
            "adapter_fetch_errors_total": 0,
            "adapter_records_fetched": 0,
            "adapter_records_rejected": 0,
            "adapter_sources_skipped": 0,
            "adapter_retries_total": 0,
        }
        self.by_source: dict[str, dict[str, int]] = {}

    def _source(self, source: str) -> dict[str, int]:
        return self.by_source.setdefault(source, {
            "fetches": 0,
            "errors": 0,
            "records_fetched": 0,
            "records_persisted": 0,
            "records_rejected": 0,
            "skips": 0,
            "retries": 0,
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

    def record_skip(self, *, source: str) -> None:
        self.counters["adapter_sources_skipped"] += 1
        self._source(source)["skips"] += 1

    def record_retry(self, *, source: str) -> None:
        self.counters["adapter_retries_total"] += 1
        self._source(source)["retries"] += 1
        research_metrics.record_retry(source)

    @property
    def snapshot(self) -> dict[str, Any]:
        return {**self.counters, "by_source": {key: dict(value) for key, value in self.by_source.items()}}


def _source_enabled() -> bool:
    return str(os.getenv("FF_PILLAR_A_SOURCE_V1", "false")).strip().lower() in {"1", "true", "yes", "on"}


def _ingestion_enabled() -> bool:
    # The scheduler owns the global gate. Fall back to the legacy source flag
    # for direct callers that predate research.sources.v1.
    if "FF_PILLAR_A_INGESTION" not in os.environ:
        return _source_enabled()
    return _flag_enabled("FF_PILLAR_A_INGESTION")


def _flag_enabled(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _source_flag_enabled(source: str) -> bool:
    if source == GoogleTrendsAdapterV1.name:
        return _flag_enabled("FF_RESEARCH_SOURCE_GOOGLE_TRENDS_V1", default=_source_enabled())
    if source == RedditResearchAdapter.name:
        return _flag_enabled("FF_RESEARCH_SOURCE_REDDIT")
    if source == MercadoLibreResearchAdapter.name:
        return _flag_enabled("FF_RESEARCH_SOURCE_MERCADOLIBRE")
    if source == YouTubeResearchAdapter.name:
        return _flag_enabled("FF_RESEARCH_SOURCE_YOUTUBE")
    if source == AmazonBestsellersResearchAdapter.name:
        return _flag_enabled("FF_RESEARCH_SOURCE_AMAZON_BESTSELLERS")
    if source == TikTokOrganicResearchAdapter.name:
        return _flag_enabled("FF_RESEARCH_SOURCE_TIKTOK_ORGANIC")
    # Injected test or extension adapters remain enabled unless their owner
    # supplies a dedicated flag in a custom registry wrapper.
    return True


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


def _source_max_retries() -> int:
    return max(0, _int_env("RESEARCH_SOURCE_MAX_RETRIES", 2))


def _source_backoff_seconds(attempt: int) -> float:
    base = max(0.0, _float_env("RESEARCH_SOURCE_BACKOFF_BASE_SECONDS", 1.0))
    return base * (2 ** attempt)


def _fetch_records(adapter: Any, *, metrics: AdapterMetrics) -> tuple[list[dict[str, Any]], int]:
    """Fetch one source with bounded retries for transient failures only."""
    retries = _source_max_retries()
    for attempt in range(retries + 1):
        try:
            records = adapter.fetch()
            if not isinstance(records, list):
                raise AdapterFetchError("schema", "research source fetch must return a list")
            return records, attempt
        except Exception as err:
            retryable = bool(getattr(err, "retryable", False)) or isinstance(
                err, (TimeoutError, ConnectionError, OSError)
            )
            if not retryable or attempt >= retries:
                raise
            metrics.record_retry(source=adapter.name)
            time.sleep(_source_backoff_seconds(attempt))
    raise RuntimeError("unreachable source retry state")


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
    registry.register(RedditResearchAdapter.name, RedditResearchAdapter())
    registry.register(MercadoLibreResearchAdapter.name, MercadoLibreResearchAdapter())
    registry.register(YouTubeResearchAdapter.name, YouTubeResearchAdapter())
    registry.register(AmazonBestsellersResearchAdapter.name, AmazonBestsellersResearchAdapter())
    registry.register(TikTokOrganicResearchAdapter.name, TikTokOrganicResearchAdapter())
    return registry


def _canonicalize_and_persist(
    adapter: Any,
    *,
    store: TrendRecordStore,
    fetched_at: datetime,
    metrics: AdapterMetrics,
) -> dict[str, int]:
    """Persist valid records while isolating malformed records in one batch."""
    started = time.perf_counter()
    try:
        raw_records, retry_count = _fetch_records(adapter, metrics=metrics)
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
        total_rejected = rejected + len(normalized) - persisted
        metrics.record_fetch(
            len(raw_records),
            source=adapter.name,
            persisted=persisted,
            rejected=total_rejected,
        )
        research_metrics.record_records(
            adapter.name,
            fetched=len(raw_records),
            persisted=persisted,
            rejected=total_rejected,
        )
        research_metrics.record_fetch(
            adapter.name,
            "succeeded",
            time.perf_counter() - started,
        )
        return {
            "fetched": len(raw_records),
            "persisted": persisted,
            "rejected": total_rejected,
            "retries": retry_count,
        }
    except Exception:
        research_metrics.record_fetch(
            adapter.name,
            "failed",
            time.perf_counter() - started,
        )
        raise


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
    ingestion_store: IngestionRunStore | None = None,
) -> None:
    """Register a fault-isolated fan-out job for every configured source."""
    adapters = adapter_registry or build_default_adapter_registry()
    record_store = store or TrendRecordStore()
    fetch_metrics = metrics or AdapterMetrics()
    run_store = ingestion_store or IngestionRunStore(path=record_store.path)

    def run_job() -> dict[str, Any]:
        if not _ingestion_enabled():
            result = {"status": "skipped", "sources": {}, "metrics": fetch_metrics.snapshot}
            run_store.append(result, window="disabled")
            return result

        started = time.perf_counter()
        fetched_at = datetime.now(timezone.utc)
        sources: dict[str, Any] = {}
        enabled_count = 0
        for name, adapter in sorted(adapters.all().items()):
            if not _source_flag_enabled(name):
                fetch_metrics.record_skip(source=name)
                sources[name] = {"status": "skipped", "reason": "feature_flag_disabled"}
                continue
            enabled_count += 1
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
                source_result: dict[str, Any] = {"status": "failed", "error": str(err)}
                if isinstance(err, AdapterFetchError):
                    source_result["error_type"] = err.error_type
                    source_result["context"] = err.context
                sources[name] = source_result
                logger.exception("research_source_failed source=%s", name)

        if enabled_count == 0:
            result = {
                "status": "skipped",
                "sources": sources,
                "metrics": fetch_metrics.snapshot,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            }
            run_store.append(result, window="empty")
            return result
        succeeded = sum(item["status"] == "succeeded" for item in sources.values())
        failed = sum(item["status"] == "failed" for item in sources.values())
        status = "succeeded" if failed == 0 else ("partial" if succeeded else "failed")
        result = {
            "status": status,
            "sources": sources,
            "metrics": fetch_metrics.snapshot,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }
        run_store.append(result, window="scheduled")
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


def build_research_registry(
    *,
    adapter_registry: ResearchAdapterRegistry | None = None,
    store: TrendRecordStore | None = None,
    max_retries: int | None = None,
    ingestion_store: IngestionRunStore | None = None,
) -> JobRegistry:
    """Build the scheduler registry used by the API research runner."""
    registry = JobRegistry(max_retries=max_retries)
    register_research_sources_job(
        registry,
        adapter_registry=adapter_registry,
        store=store,
        ingestion_store=ingestion_store,
    )
    register_research_prune_job(registry, store=store)
    return registry
