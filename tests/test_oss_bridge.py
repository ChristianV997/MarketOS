import asyncio

from backend.commerce.oss_bridge import clear_oss_cache, collect_oss_inputs
from backend.commerce.loop import run_provider_cycle
from backend.contracts.adapters import AdapterHealth, SidecarContext
from backend.adapters.research.crawl4ai import Crawl4AIResearchAdapter


class Research:
    async def discover(self, url, *, context):
        return [{"name": "Bridge Product", "url": url, "quality": {"provenance": "live"}}]


class Commerce:
    configured = False

    def list_products(self, *, limit=50):
        raise AssertionError("unconfigured commerce must not be called")


def test_oss_bridge_feeds_canonical_signal_inputs_and_degrades_safely():
    clear_oss_cache()
    signals, products, metadata = collect_oss_inputs(
        ["https://supplier.example/item"],
        research=Research(), commerce=Commerce(), context=SidecarContext(dry_run=False),
    )
    assert signals[0]["product"] == "Bridge Product"
    assert products == {}
    assert metadata["failures"] == {}


def test_oss_bridge_marks_live_attributed_research_and_preserves_economics():
    # Verify the conversion helper directly to isolate source-quality semantics.
    from backend.commerce.oss_bridge import _research_signal
    normalized = _research_signal({
        "name": "Attributed Product", "url": "https://source.example/p",
        "price": 29.0, "unit_cost": 8.0, "quality": {"provenance": "live"},
    })
    assert normalized["quality"]["attribution"] == "attributed"
    assert normalized["price"] == 29.0
    assert normalized["unit_cost"] == 8.0
    assert normalized["metadata"]["currency"] == "USD"


def test_oss_bridge_preserves_typed_crawl4ai_candidate_for_ranking():
    clear_oss_cache()

    class StructuredResearch(Crawl4AIResearchAdapter):
        async def discover(self, url, *, context):
            return [{
                "name": "Travel Mug", "product_id": "mug-blue", "url": url,
                "selling_price": 19.95, "unit_cost": 6.5, "shipping_cost": 2, "currency": "USD",
                "quality": {"provenance": "live", "attribution": "attributed", "source_ref": url},
            }]

    signals, products, metadata = collect_oss_inputs(
        ["https://supplier.example/mug"], research=StructuredResearch(), commerce=Commerce(), context=SidecarContext(dry_run=False),
    )
    assert signals[0]["product_id"] == "mug-blue"
    assert products["mug-blue"].selling_price == 19.95
    assert metadata["research_products"] == 1
    assert metadata["offers"]["mug-blue"].unit_cost == 6.5
    assert metadata["research_offers"] == 1


class FailingResearch:
    async def discover(self, url, *, context):
        raise RuntimeError("source unavailable")


def test_oss_bridge_reports_provider_failure_without_live_evidence():
    clear_oss_cache()
    signals, products, metadata = collect_oss_inputs(
        ["https://supplier.example/item"], research=FailingResearch(), commerce=Commerce()
    )
    assert signals == []
    assert "research:https://supplier.example/item" in metadata["failures"]


def test_oss_bridge_caches_successful_research_results():
    clear_oss_cache()

    class CountingResearch:
        calls = 0
        async def discover(self, url, *, context):
            self.calls += 1
            return [{"name": "Cached Product", "url": url}]

    research = CountingResearch()
    collect_oss_inputs(["https://supplier.example/cached"], research=research, commerce=Commerce())
    collect_oss_inputs(["https://supplier.example/cached"], research=research, commerce=Commerce())
    assert research.calls == 1


def test_oss_bridge_bounds_concurrent_research_refreshes(monkeypatch):
    clear_oss_cache()
    monkeypatch.setenv("MARKETOS_OSS_MAX_CONCURRENCY", "2")

    class ConcurrentResearch:
        active = 0
        peak = 0

        async def discover(self, url, *, context):
            self.active += 1
            self.peak = max(self.peak, self.active)
            await asyncio.sleep(0.01)
            self.active -= 1
            return [{"name": url.rsplit("/", 1)[-1], "url": url}]

    research = ConcurrentResearch()
    signals, _, metadata = collect_oss_inputs(
        ["https://supplier.example/a", "https://supplier.example/b", "https://supplier.example/c"],
        research=research, commerce=Commerce(),
    )
    assert [item["product"] for item in signals] == ["a", "b", "c"]
    assert research.peak == 2
    assert metadata["failures"] == {}


def test_oss_bridge_retries_transient_research_failure():
    clear_oss_cache()

    class FlakyResearch:
        calls = 0
        async def discover(self, url, *, context):
            self.calls += 1
            if self.calls < 3:
                raise TimeoutError("temporary timeout")
            return [{"name": "Recovered Product", "url": url}]

    research = FlakyResearch()
    signals, _, metadata = collect_oss_inputs(
        ["https://supplier.example/flaky"], research=research, commerce=Commerce()
    )
    assert len(signals) == 1
    assert research.calls == 3
    assert metadata["failures"] == {}


def test_oss_bridge_does_not_retry_permission_failure(monkeypatch):
    clear_oss_cache()

    class ForbiddenResearch:
        calls = 0
        async def discover(self, url, *, context):
            self.calls += 1
            raise PermissionError("blocked domain")

    research = ForbiddenResearch()
    signals, _, metadata = collect_oss_inputs(
        ["https://supplier.example/blocked"], research=research, commerce=Commerce()
    )
    assert signals == []
    assert research.calls == 1
    assert "research:https://supplier.example/blocked" in metadata["failures"]


def test_oss_bridge_separates_dry_run_and_live_cache_entries():
    clear_oss_cache()

    class ModeResearch:
        calls = []
        async def discover(self, url, *, context):
            self.calls.append(context.dry_run)
            return [{"name": "Dry" if context.dry_run else "Live", "url": url}]

    research = ModeResearch()
    collect_oss_inputs(["https://supplier.example/mode"], research=research, commerce=Commerce(), context=SidecarContext(dry_run=True))
    signals, _, _ = collect_oss_inputs(["https://supplier.example/mode"], research=research, commerce=Commerce(), context=SidecarContext(dry_run=False))
    assert signals[0]["product"] == "Live"
    assert research.calls == [True, False]


def test_provider_cycle_uses_one_canonical_commerce_execution_path():
    clear_oss_cache()
    report = run_provider_cycle(
        ["https://supplier.example/cycle"],
        research_provider=Research(), commerce_provider=Commerce(),
        context=SidecarContext(dry_run=True), top_k=1, budget=10.0, dry_run=True,
    )
    assert report.dry_run is True
    assert report.summary["provider_signals"] == 1
    assert report.summary["ranked"] == 1
    assert report.summary["creatives"] == 1


def test_oss_provider_metrics_are_exported_when_prometheus_is_available():
    import pytest
    pytest.importorskip("prometheus_client")
    clear_oss_cache()
    collect_oss_inputs(["https://supplier.example/metrics"], research=Research(), commerce=Commerce())
    from backend.api import prometheus_metrics
    payload = prometheus_metrics().body.decode()
    assert "marketos_oss_provider_refreshes_total" in payload
    assert "marketos_oss_provider_refresh_duration_seconds" in payload
