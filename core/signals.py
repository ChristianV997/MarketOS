import random
import os
import time
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
except ImportError:
    _prom_signal_cache_hits = None
    _prom_signal_cache_lookups = None
    _prom_signal_cache_refreshes = None
    _prom_signal_cache_refresh_duration = None
    _prom_signal_cache_last_refresh_duration = None
    _prom_signal_source_failures = None


class SignalEngine:
    """Aggregates external demand signals and scores product opportunities."""

    def __init__(self):
        self._sources: list = []
        # Signal adapters include remote APIs and scraping-backed sources.  A
        # short process-local cache lets dashboard/snapshot consumers share an
        # ingestion result instead of repeating those calls per request.
        self._cache_ttl_s = max(0.0, float(os.getenv("SIGNAL_CACHE_TTL_S", "60")))
        self._cached_signals: list[dict] = []
        self._cache_updated_at = 0.0
        self._cache_lookups = 0
        self._cache_hits = 0
        self._refresh_count = 0
        self._last_refresh_duration_s = 0.0
        self._last_refresh_at = 0.0
        self._source_failures: dict[str, int] = {}

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
            "cache_lookups": lookups,
            "cache_hits": self._cache_hits,
            "cache_hit_rate": round(self._cache_hits / lookups, 4) if lookups else 0.0,
            "refresh_count": self._refresh_count,
            "last_refresh_duration_s": round(self._last_refresh_duration_s, 4),
            "last_refresh_at": self._last_refresh_at or None,
            "cached_signal_count": len(self._cached_signals),
            "source_failures": dict(self._source_failures),
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

        refresh_started = time.monotonic()
        if not self._sources:
            signals = self._mock_signals()
            self._cached_signals = self._copy_signals(signals)
            self._cache_updated_at = now
            self._refresh_count += 1
            self._record_refresh_metrics(time.monotonic() - refresh_started)
            self._last_refresh_at = time.time()
            return signals

        all_signals: list = []
        for source in self._sources:
            try:
                signals = source["fetch"]()
                for s in signals:
                    s.setdefault("source", source["name"])
                all_signals.extend(signals)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                source_name = str(source.get("name") or "unknown")
                self._source_failures[source_name] = self._source_failures.get(source_name, 0) + 1
                if _prom_signal_source_failures is not None:
                    _prom_signal_source_failures.labels(source=source_name).inc()

        signals = all_signals if all_signals else self._mock_signals()
        self._cached_signals = self._copy_signals(signals)
        self._cache_updated_at = now
        self._refresh_count += 1
        self._record_refresh_metrics(time.monotonic() - refresh_started)
        self._last_refresh_at = time.time()
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

    def top_opportunities(self, signals: list, n: int = 5) -> list:
        """Return the top N signals by score."""
        return sorted(signals, key=lambda s: s.get("score", 0), reverse=True)[:n]


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
    # Google Trends adapter via existing research adapter registry
    try:
        from backend.adapters.research import GoogleTrendsAdapterV1
        from datetime import datetime, timezone
        def _google_trends_fetch():
            adapter = GoogleTrendsAdapterV1()
            raw = adapter.fetch()
            return [
                {
                    "product":  adapter.to_canonical(r, fetched_at=datetime.now(timezone.utc)).keyword,
                    "score":    getattr(adapter.to_canonical(r, fetched_at=datetime.now(timezone.utc)), "confidence", 0.6),
                    "velocity": getattr(adapter.to_canonical(r, fetched_at=datetime.now(timezone.utc)), "velocity", 1.0),
                    "source":   "google_trends",
                    "platform": "google",
                }
                for r in raw
            ]
        signal_engine.register_source("google_trends", _google_trends_fetch)
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


_register_adapters()
