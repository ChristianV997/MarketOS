import random
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Callable

try:
    from prometheus_client import Counter, Gauge, Histogram

    _prom_signal_cache_hits = Counter(
        "marketos_signal_cache_hits",
        "Signal cache lookups served without external refresh",
    )
    _prom_signal_cache_lookups = Counter(
        "marketos_signal_cache_lookups",
        "Signal cache lookup operations",
    )
    _prom_signal_cache_refreshes = Counter(
        "marketos_signal_cache_refreshes",
        "Signal cache refresh operations",
    )
    _prom_signal_cache_refresh_duration = Histogram(
        "marketos_signal_cache_refresh_duration_seconds",
        "Duration of aggregated signal refreshes",
    )
    _prom_signal_cache_last_refresh_duration = Gauge(
        "marketos_signal_cache_last_refresh_duration_seconds",
        "Duration of the most recent aggregated signal refresh",
    )
    _prom_signal_source_failures = Counter(
        "marketos_signal_source_failures",
        "Signal source refresh failures",
        ["source"],
    )
    _prom_signal_source_successes = Counter(
        "marketos_signal_source_successes",
        "Signal source refresh successes",
        ["source"],
    )
    _prom_signal_source_refresh_duration = Histogram(
        "marketos_signal_source_refresh_duration_seconds",
        "Duration of individual signal source refreshes",
        ["source"],
    )
except ImportError:
    _prom_signal_cache_hits = None
    _prom_signal_cache_lookups = None
    _prom_signal_cache_refreshes = None
    _prom_signal_cache_refresh_duration = None
    _prom_signal_cache_last_refresh_duration = None
    _prom_signal_source_failures = None
    _prom_signal_source_successes = None
    _prom_signal_source_refresh_duration = None


class SignalEngine:
    """Aggregates external demand signals and scores product opportunities."""

    def __init__(self):
        self._sources: list = []
        # Signal adapters include remote APIs and scraping-backed sources.  A
        # short process-local cache lets dashboard/snapshot consumers share an
        # ingestion result instead of repeating those calls per request.
        self._cache_ttl_s = max(0.0, float(os.getenv("SIGNAL_CACHE_TTL_S", "60")))
        self._source_timeout_s = max(0.1, float(os.getenv("SIGNAL_SOURCE_TIMEOUT_S", "15")))
        self._max_source_workers = max(1, int(os.getenv("SIGNAL_SOURCE_MAX_WORKERS", "4")))
        self._refresh_lock = threading.Lock()
        self._cached_signals: list[dict] = []
        self._cache_updated_at = 0.0
        self._cache_lookups = 0
        self._cache_hits = 0
        self._refresh_count = 0
        self._last_refresh_duration_s = 0.0
        self._last_refresh_at = 0.0
        self._source_failures: dict[str, int] = {}
        self._source_successes: dict[str, int] = {}
        self._source_refresh_duration_s: dict[str, float] = {}
        self._source_last_refresh_at: dict[str, float] = {}

    def register_source(self, name: str, fetch_fn: Callable) -> None:
        """Register a named signal source callable."""
        self._sources.append({"name": name, "fetch": fetch_fn})
        self.clear_cache()

    def clear_cache(self) -> None:
        """Discard the latest aggregated result before an explicit ingestion."""
        self._cached_signals = []
        self._cache_updated_at = 0.0

    def cache_stats(self) -> dict:
        """Return operational cache and source-health telemetry."""
        lookups = self._cache_lookups
        return {
            "cache_ttl_s": self._cache_ttl_s,
            "source_timeout_s": self._source_timeout_s,
            "source_max_workers": self._max_source_workers,
            "cache_lookups": lookups,
            "cache_hits": self._cache_hits,
            "cache_hit_rate": round(self._cache_hits / lookups, 4) if lookups else 0.0,
            "refresh_count": self._refresh_count,
            "last_refresh_duration_s": round(self._last_refresh_duration_s, 4),
            "last_refresh_at": self._last_refresh_at or None,
            "cached_signal_count": len(self._cached_signals),
            "source_failures": dict(self._source_failures),
            "source_successes": dict(self._source_successes),
            "source_refresh_duration_s": dict(self._source_refresh_duration_s),
            "source_last_refresh_at": dict(self._source_last_refresh_at),
            "source_failure_total": sum(self._source_failures.values()),
        }

    @staticmethod
    def _copy_signals(signals: list[dict]) -> list[dict]:
        """Keep callers from mutating the cache's shared signal records."""
        return [dict(signal) for signal in signals]

    def _mock_signals(self) -> list:
        """Fallback mock signals when no real sources are configured."""
        return [
            {
                "product": f"product_{i}",
                "score": round(random.uniform(0.3, 1.0), 2),
                "source": "mock",
                "market": "global",
                "platform": "meta",
            }
            for i in range(3)
        ]

    def get(self, *, force_refresh: bool = False) -> list:
        """Fetch and aggregate signals, reusing a bounded recent result.

        ``force_refresh`` is intended for ingestion workers. Read-only paths
        such as API snapshots and content planning should use the cache so a
        single user request cannot fan out into every external adapter.
        """
        now = time.monotonic()
        self._cache_lookups += 1
        if _prom_signal_cache_lookups is not None:
            _prom_signal_cache_lookups.inc()
        if (
            not force_refresh
            and self._cached_signals
            and now - self._cache_updated_at < self._cache_ttl_s
        ):
            self._cache_hits += 1
            if _prom_signal_cache_hits is not None:
                _prom_signal_cache_hits.inc()
            return self._copy_signals(self._cached_signals)

        # Only one caller may refresh external sources at a time. Re-check
        # after waiting so concurrent scheduler/API callers share the result
        # instead of fanning out into duplicate provider requests.
        refresh_generation = self._cache_updated_at
        self._refresh_lock.acquire()
        try:
            now = time.monotonic()
            if self._cached_signals and self._cache_updated_at != refresh_generation:
                self._refresh_lock.release()
                return self._copy_signals(self._cached_signals)
            if (
                not force_refresh
                and self._cached_signals
                and now - self._cache_updated_at < self._cache_ttl_s
            ):
                self._cache_hits += 1
                if _prom_signal_cache_hits is not None:
                    _prom_signal_cache_hits.inc()
                self._refresh_lock.release()
                return self._copy_signals(self._cached_signals)

            # The lock remains held through the refresh below. This is
            # intentional: a second caller must wait and reuse this result.
        except BaseException:
            self._refresh_lock.release()
            raise

        refresh_started = time.monotonic()
        if not self._sources:
            signals = self._mock_signals()
            self._cached_signals = self._copy_signals(signals)
            self._cache_updated_at = now
            self._refresh_count += 1
            self._record_refresh_metrics(time.monotonic() - refresh_started)
            self._last_refresh_at = time.time()
            self._refresh_lock.release()
            return signals

        from backend.discovery.registry import discovery_registry

        all_signals: list = []

        def fetch_source(source: dict) -> tuple[str, list[dict], float, str | None]:
            source_name = str(source.get("name") or "unknown")
            started = time.monotonic()
            try:
                fetched = source["fetch"]() or []
                signals = [dict(signal) for signal in fetched]
                for signal in signals:
                    signal.setdefault("source", source_name)
                discovery_registry.record_fetch(source_name, len(signals))
                return source_name, signals, time.monotonic() - started, None
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:
                discovery_registry.record_fetch(source_name, 0, error=str(exc))
                return source_name, [], time.monotonic() - started, str(exc)

        workers = min(self._max_source_workers, max(1, len(self._sources)))
        executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="marketos-signal")
        futures = [executor.submit(fetch_source, source) for source in self._sources]
        try:
            for source, future in zip(self._sources, futures):
                source_name = str(source.get("name") or "unknown")
                try:
                    name, signals, duration, error = future.result(timeout=self._source_timeout_s)
                except FutureTimeoutError:
                    name, signals, duration, error = source_name, [], self._source_timeout_s, "source timeout"
                self._source_refresh_duration_s[name] = round(duration, 4)
                self._source_last_refresh_at[name] = time.time()
                if _prom_signal_source_refresh_duration is not None:
                    _prom_signal_source_refresh_duration.labels(source=name).observe(duration)
                if error:
                    self._source_failures[name] = self._source_failures.get(name, 0) + 1
                    if _prom_signal_source_failures is not None:
                        _prom_signal_source_failures.labels(source=name).inc()
                    continue
                self._source_successes[name] = self._source_successes.get(name, 0) + 1
                if _prom_signal_source_successes is not None:
                    _prom_signal_source_successes.labels(source=name).inc()
                all_signals.extend(signals)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        signals = all_signals if all_signals else self._mock_signals()
        self._cached_signals = self._copy_signals(signals)
        self._cache_updated_at = now
        self._refresh_count += 1
        self._record_refresh_metrics(time.monotonic() - refresh_started)
        self._last_refresh_at = time.time()
        self._refresh_lock.release()
        return self._copy_signals(signals)

    def _record_refresh_metrics(self, duration_s: float) -> None:
        self._last_refresh_duration_s = duration_s
        if _prom_signal_cache_refreshes is not None:
            _prom_signal_cache_refreshes.inc()
            _prom_signal_cache_refresh_duration.observe(duration_s)
            _prom_signal_cache_last_refresh_duration.set(duration_s)

    def filter_opportunities(self, signals: list, min_score: float = 0.5) -> list:
        """Return only signals that meet the minimum score threshold."""
        return [s for s in signals if s.get("score", 0) >= min_score]

    def top_opportunities(self, signals: list, n: int = 5, use_urgency: bool = False) -> list:
        """Return top N signals by score, optionally weighted by urgency (Phase 7).

        If use_urgency=True, rank by urgency = score * velocity * (1 - saturation).
        This prioritizes products that are trending fast with low market saturation.
        """
        if not use_urgency:
            return sorted(signals, key=lambda s: s.get("score", 0), reverse=True)[:n]

        ranked = []
        for s in signals:
            base_score = s.get("score", 0)
            velocity = s.get("velocity", 0.5)  # default 0.5 if not provided
            saturation = s.get("saturation", 0.5)  # default 0.5 if not provided
            urgency = base_score * velocity * (1 - saturation)
            ranked.append((s, urgency))

        return [s for s, _ in sorted(ranked, key=lambda x: -x[1])[:n]]


signal_engine = SignalEngine()

# ── auto-register real adapters ───────────────────────────────────────────────
# Each adapter registers itself if importable; no-op on ImportError.
def _register_adapters() -> None:
    try:
        from backend.adapters.amazon_bestsellers import register as _r1
        _r1(signal_engine)
    except Exception:
        pass
    try:
        from backend.adapters.tiktok_organic import register as _r2
        _r2(signal_engine)
    except Exception:
        pass
    try:
        from backend.adapters.research.trend_source_v1 import register as _r_google
        _r_google(signal_engine)
    except Exception:
        pass
    try:
        from backend.adapters.reddit_trends import register as _r3
        _r3(signal_engine)
    except Exception:
        pass
    try:
        from backend.adapters.youtube_trends import register as _r4
        _r4(signal_engine)
    except Exception:
        pass
    try:
        from backend.adapters.mercadolibre_trends import register as _r5
        _r5(signal_engine)
    except Exception:
        pass
    try:
        from backend.adapters.alibaba_trends import register as _r6
        _r6(signal_engine)
    except Exception:
        pass


_register_adapters()
