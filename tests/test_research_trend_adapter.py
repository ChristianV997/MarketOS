from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backend.adapters.research import (
    AdapterFetchError,
    GoogleTrendsAdapterV1,
    MercadoLibreResearchAdapter,
    ResearchAdapterRegistry,
    RedditResearchAdapter,
    classify_http_error,
)
from backend.jobs.research_trend_v1 import (
    AdapterMetrics,
    build_research_registry,
    register_research_sources_job,
    register_research_trend_v1_job,
)
from backend.jobs.runner import JobRegistry
from backend.research import TrendRecordStore


def test_trend_mapping_transforms_payload_to_canonical_entity():
    adapter = GoogleTrendsAdapterV1(max_pages=1)
    fetched_at = datetime(2026, 1, 1, 10, 30, tzinfo=timezone.utc)
    raw = {
        "title": {"query": "best buy laptop deals"},
        "formattedTraffic": "200K+",
        "articles": [{"title": "a"}, {"title": "b"}],
    }

    record = adapter.to_canonical(raw, fetched_at=fetched_at)

    assert record["topic"] == "best buy laptop deals"
    assert record["intent"] == "buy"
    assert record["velocity"] == 199.0
    assert record["competition"] == 0.2
    assert record["source"] == "google_trends_v1"
    assert record["freshness_ts"] == fetched_at.isoformat()
    assert record["confidence"] == 0.7
    assert record["raw"] == raw


def test_to_canonical_non_dict_title_raises_adapter_error_not_attributeerror():
    """A malformed upstream record can have "title" present but not a dict
    (e.g. a bare string). Previously raw_record.get("title", {}).get(...)
    would raise AttributeError in that case, which the only caller
    (fetch_google_trends_signals) doesn't catch — crashing the whole
    adapter fetch loop instead of skipping the one bad record."""
    adapter = GoogleTrendsAdapterV1(max_pages=1)
    raw = {"title": "not-a-dict", "formattedTraffic": "50K+", "articles": []}

    with pytest.raises(AdapterFetchError):
        adapter.to_canonical(raw)


class TestTrendspygFetch:
    """trendspyg's RSS downloader (no Selenium/browser needed) replaced the
    hand-scrape of Google's undocumented dailytrends endpoint as the
    primary fetch path — to_canonical()'s intent/velocity/competition
    derivation is unchanged, only the data source."""

    def test_fetch_uses_trendspyg_when_available(self, monkeypatch):
        import backend.adapters.research.trend_source_v1 as mod

        if mod._trendspyg is None:
            monkeypatch.setattr(mod, "_trendspyg", SimpleNamespace())

        fake_trends = [
            {
                "trend": "best buy laptop deals",
                "traffic": "200K+",
                "news_articles": [{"headline": "a"}, {"headline": "b"}],
            },
        ]
        monkeypatch.setattr(
            mod._trendspyg, "download_google_trends_rss",
            lambda **kw: fake_trends,
            raising=False,
        )

        adapter = mod.GoogleTrendsAdapterV1(max_pages=1)
        records = adapter.fetch()

        assert records == [{
            "title": {"query": "best buy laptop deals"},
            "formattedTraffic": "200K+",
            "articles": [{"headline": "a"}, {"headline": "b"}],
        }]
        # to_canonical() is unchanged and still parses this reshaped record
        canonical = adapter.to_canonical(records[0])
        assert canonical["topic"] == "best buy laptop deals"
        assert canonical["intent"] == "buy"

    def test_fetch_falls_back_to_legacy_on_trendspyg_failure(self, monkeypatch):
        import backend.adapters.research.trend_source_v1 as mod

        if mod._trendspyg is None:
            monkeypatch.setattr(mod, "_trendspyg", SimpleNamespace())

        def _boom(**kw):
            raise RuntimeError("trendspyg network error")

        monkeypatch.setattr(mod._trendspyg, "download_google_trends_rss", _boom, raising=False)

        legacy_calls = []
        monkeypatch.setattr(
            mod.GoogleTrendsAdapterV1, "_fetch_legacy",
            lambda self: legacy_calls.append(1) or [],
        )

        adapter = mod.GoogleTrendsAdapterV1(max_pages=1)
        records = adapter.fetch()

        assert records == []
        assert legacy_calls == [1]

    def test_fetch_uses_legacy_path_when_trendspyg_unavailable(self, monkeypatch):
        import backend.adapters.research.trend_source_v1 as mod
        monkeypatch.setattr(mod, "_trendspyg", None)

        legacy_calls = []
        monkeypatch.setattr(
            mod.GoogleTrendsAdapterV1, "_fetch_legacy",
            lambda self: legacy_calls.append(1) or [],
        )

        adapter = mod.GoogleTrendsAdapterV1(max_pages=1)
        records = adapter.fetch()

        assert records == []
        assert legacy_calls == [1]


def test_error_classification_for_http_status_codes():
    assert classify_http_error(429) == "rate_limit"
    assert classify_http_error(503) == "server"
    assert classify_http_error(401) == "auth"
    assert classify_http_error(403) == "auth"


def test_non_retryable_adapter_error_does_not_retry(monkeypatch):
    sleeps = []
    attempts = {"count": 0}

    def fake_sleep(seconds):
        sleeps.append(seconds)

    def schema_fail_job():
        attempts["count"] += 1
        raise AdapterFetchError("schema", "invalid payload")

    monkeypatch.setattr("backend.jobs.runner.time.sleep", fake_sleep)
    registry = JobRegistry(max_retries=3)
    registry.register("research.trend.v1", schema_fail_job)

    result = registry.run("research.trend.v1")
    assert result["status"] == "failed"
    assert attempts["count"] == 1
    assert sleeps == []


def test_mocked_fetch_path_persists_normalized_records(tmp_path, monkeypatch):
    os_env = {"FF_PILLAR_A_SOURCE_V1": "true"}
    for key, value in os_env.items():
        monkeypatch.setenv(key, value)

    class FakeAdapter:
        name = "google_trends_v1"

        def fetch(self):
            return [
                {
                    "title": {"query": "compare ai tools"},
                    "formattedTraffic": "50K+",
                    "articles": [{"title": "a"}],
                }
            ]

        def to_canonical(self, raw_record, fetched_at=None):
            return {
                "topic": raw_record["title"]["query"],
                "intent": "compare",
                "velocity": 49.0,
                "competition": 0.1,
                "source": self.name,
                "freshness_ts": (fetched_at or datetime.now(timezone.utc)).isoformat(),
                "confidence": 0.7,
                "raw": raw_record,
            }

    adapters = ResearchAdapterRegistry()
    adapters.register("google_trends_v1", FakeAdapter())

    store_path = tmp_path / "research.db"
    store = TrendRecordStore(path=str(store_path))
    registry = JobRegistry(max_retries=0)
    register_research_trend_v1_job(registry, adapter_registry=adapters, store=store)

    result = registry.run("research.trend.v1")

    assert result["status"] == "succeeded"
    persisted = store.findTopN(1)[0]
    assert persisted["topic"] == "compare ai tools"
    assert persisted["intent"] == "compare"
    assert persisted["source"] == "google_trends_v1"
    assert "freshness_ts" in persisted
    assert "confidence" in persisted
    assert "velocity" in persisted
    assert "dedupe_key" in persisted


def test_feature_flag_disables_adapter_execution(monkeypatch):
    monkeypatch.setenv("FF_PILLAR_A_SOURCE_V1", "false")
    called = {"count": 0}

    class FakeAdapter:
        name = "google_trends_v1"

        def fetch(self):
            called["count"] += 1
            return []

        def to_canonical(self, raw_record, fetched_at=None):
            return raw_record

    adapters = ResearchAdapterRegistry()
    adapters.register("google_trends_v1", FakeAdapter())
    registry = JobRegistry(max_retries=0)
    register_research_trend_v1_job(registry, adapter_registry=adapters, store=TrendRecordStore(path="/tmp/research.jsonl"))

    result = registry.run("research.trend.v1")
    assert result["status"] == "succeeded"
    assert called["count"] == 0


def test_malformed_record_does_not_discard_valid_records(tmp_path, monkeypatch):
    monkeypatch.setenv("FF_PILLAR_A_SOURCE_V1", "true")

    class FakeAdapter:
        name = "google_trends_v1"

        def fetch(self):
            return [{"valid": True}, {"valid": False}]

        def to_canonical(self, raw_record, fetched_at=None):
            if not raw_record["valid"]:
                raise AdapterFetchError("schema", "malformed record")
            return {
                "topic": "valid topic",
                "intent": "research",
                "velocity": 1.0,
                "competition": 0.1,
                "source": self.name,
                "freshness_ts": (fetched_at or datetime.now(timezone.utc)).isoformat(),
                "confidence": 0.7,
                "raw": raw_record,
            }

    adapters = ResearchAdapterRegistry()
    adapters.register("google_trends_v1", FakeAdapter())
    metrics = AdapterMetrics()
    store = TrendRecordStore(path=str(tmp_path / "research.db"))
    registry = JobRegistry(max_retries=0)
    register_research_trend_v1_job(registry, adapter_registry=adapters, store=store, metrics=metrics)

    result = registry.run("research.trend.v1")

    assert result["status"] == "succeeded"
    assert len(store.findTopN(10)) == 1
    assert metrics.counters["adapter_records_rejected"] == 1
    assert metrics.by_source["google_trends_v1"]["records_persisted"] == 1


def test_source_fanout_isolates_source_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("FF_PILLAR_A_SOURCE_V1", "true")

    class GoodAdapter:
        name = "good"

        def fetch(self):
            return [{"topic": "good topic"}]

        def to_canonical(self, raw_record, fetched_at=None):
            return {
                "topic": raw_record["topic"],
                "intent": "buy",
                "velocity": 2.0,
                "competition": 0.1,
                "source": self.name,
                "freshness_ts": (fetched_at or datetime.now(timezone.utc)).isoformat(),
                "confidence": 0.8,
                "raw": raw_record,
            }

    class BrokenAdapter:
        name = "broken"

        def fetch(self):
            raise AdapterFetchError("server", "source unavailable")

    adapters = ResearchAdapterRegistry()
    adapters.register("good", GoodAdapter())
    adapters.register("broken", BrokenAdapter())
    store = TrendRecordStore(path=str(tmp_path / "research.db"))

    class CapturingRegistry:
        def register(self, name, handler):
            self.handler = handler

    registry = CapturingRegistry()
    register_research_sources_job(registry, adapter_registry=adapters, store=store)
    result = registry.handler()

    assert result["status"] == "partial"
    assert result["sources"]["good"]["status"] == "succeeded"
    assert result["sources"]["broken"]["status"] == "failed"
    assert len(store.findTopN(10)) == 1


@pytest.mark.parametrize(
    ("adapter_class", "signal"),
    [
        (RedditResearchAdapter, {"product": "best desk lamp", "velocity": 0.8}),
        (MercadoLibreResearchAdapter, {"product": "wireless earbuds", "velocity": 0.6}),
    ],
)
def test_public_market_adapters_preserve_unknown_competition(adapter_class, signal):
    record = adapter_class().to_canonical(signal, fetched_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert record["topic"] == signal["product"]
    assert record["competition"] is None
    assert record["raw"]["competition_evidence"] == "unavailable"


def test_source_flags_skip_new_sources_but_preserve_google_compatibility(monkeypatch, tmp_path):
    monkeypatch.setenv("FF_PILLAR_A_INGESTION", "true")
    monkeypatch.setenv("FF_PILLAR_A_SOURCE_V1", "true")
    monkeypatch.delenv("FF_RESEARCH_SOURCE_GOOGLE_TRENDS_V1", raising=False)
    monkeypatch.delenv("FF_RESEARCH_SOURCE_REDDIT", raising=False)
    monkeypatch.delenv("FF_RESEARCH_SOURCE_MERCADOLIBRE", raising=False)

    class CapturingRegistry:
        def register(self, name, handler):
            self.handler = handler

    registry = CapturingRegistry()
    adapters = ResearchAdapterRegistry()
    adapters.register("google_trends_v1", type("Google", (), {
        "name": "google_trends_v1",
        "fetch": lambda self: [],
        "to_canonical": lambda self, raw, fetched_at=None: raw,
    })())
    adapters.register("reddit", RedditResearchAdapter())
    adapters.register("mercadolibre", MercadoLibreResearchAdapter())
    register_research_sources_job(registry, adapter_registry=adapters, store=TrendRecordStore(path=str(tmp_path / "research.db")))

    result = registry.handler()
    assert result["status"] == "succeeded"
    assert result["sources"]["google_trends_v1"]["status"] == "succeeded"
    assert result["sources"]["reddit"]["status"] == "skipped"
    assert result["sources"]["mercadolibre"]["status"] == "skipped"


def test_global_ingestion_flag_overrides_legacy_source_flag(monkeypatch, tmp_path):
    monkeypatch.setenv("FF_PILLAR_A_SOURCE_V1", "true")
    monkeypatch.setenv("FF_PILLAR_A_INGESTION", "false")
    class CapturingRegistry:
        def register(self, name, handler):
            self.handler = handler

    registry = CapturingRegistry()
    register_research_sources_job(
        registry,
        adapter_registry=ResearchAdapterRegistry(),
        store=TrendRecordStore(path=str(tmp_path / "research.db")),
    )

    assert registry.handler()["status"] == "skipped"


def test_research_registry_schedules_fanout_and_prune(tmp_path):
    registry = build_research_registry(store=TrendRecordStore(path=str(tmp_path / "research.db")), max_retries=0)
    assert set(registry._handlers) == {"research.sources.v1", "research.prune"}
