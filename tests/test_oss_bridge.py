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
