from backend.commerce.oss_bridge import clear_oss_cache, collect_oss_inputs
from backend.contracts.adapters import AdapterHealth, SidecarContext


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
