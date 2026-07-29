import pytest
import sys
import types

from backend.adapters.research.crawl4ai import Crawl4AIResearchAdapter
from backend.contracts.adapters import SidecarContext
from backend.integrations.browser_use_worker import BrowserUseWorker


def test_crawl4ai_is_optional_and_dry_run_is_network_free():
    adapter = Crawl4AIResearchAdapter()
    result = pytest.importorskip("asyncio").run(
        adapter.discover("https://example.com/product", context=SidecarContext(dry_run=True))
    )
    assert result[0]["dry_run"] is True
    assert adapter.health().name == "crawl4ai"


def test_browser_worker_requires_allowlisted_workflow_and_approval():
    worker = BrowserUseWorker()
    with pytest.raises(PermissionError):
        pytest.importorskip("asyncio").run(
            worker.execute("checkout", {}, context=SidecarContext(dry_run=True))
        )


def test_browser_worker_dry_run_returns_plan():
    worker = BrowserUseWorker()
    result = pytest.importorskip("asyncio").run(
        worker.execute("supplier_research", {"query": "travel mug"}, context=SidecarContext(dry_run=True))
    )
    assert result["status"] == "planned"
    assert result["dry_run"] is True


def test_browser_worker_rejects_non_allowlisted_domain():
    worker = BrowserUseWorker(allowed_domains={"supplier.example"})
    with pytest.raises(PermissionError):
        pytest.importorskip("asyncio").run(
            worker.execute("supplier_research", {"url": "https://other.example/item"}, context=SidecarContext(dry_run=True))
        )


def test_browser_worker_requires_trace_for_live_runner():
    async def runner(_workflow, _payload, _context):
        return {"status": "done"}
    worker = BrowserUseWorker(runner=runner)
    with pytest.raises(RuntimeError, match="execution trace"):
        pytest.importorskip("asyncio").run(
            worker.execute("supplier_research", {}, context=SidecarContext(dry_run=False, approval_state="approved"))
        )


def test_browser_use_runner_is_lazy_and_optional(monkeypatch):
    monkeypatch.setitem(sys.modules, "browser_use", None)
    with pytest.raises(RuntimeError, match="not installed"):
        from backend.integrations.browser_use_worker import build_browser_use_runner
        build_browser_use_runner()


def test_crawl4ai_rejects_non_allowlisted_live_domain():
    adapter = Crawl4AIResearchAdapter(allowed_domains={"example.com"})
    with pytest.raises(PermissionError):
        pytest.importorskip("asyncio").run(
            adapter.discover("https://evil.example/test", context=SidecarContext(dry_run=False))
        )


def test_crawl4ai_requires_allowlist_for_live_research():
    adapter = Crawl4AIResearchAdapter(allowed_domains=set())
    with pytest.raises(PermissionError, match="requires CRAWL4AI_ALLOWED_DOMAINS"):
        pytest.importorskip("asyncio").run(
            adapter.discover("https://supplier.example/item", context=SidecarContext(dry_run=False))
        )


def test_crawl4ai_normalizes_only_named_records_to_marketos_contract():
    candidates = Crawl4AIResearchAdapter.normalize_candidates([
        {"name": "Travel Mug", "url": "https://supplier.example/mug", "price": "19.95", "quality": {"provenance": "live"}},
        {"content": "not a product"},
    ])
    assert len(candidates) == 1
    assert candidates[0].name == "Travel Mug"
    assert candidates[0].selling_price == 19.95
    assert candidates[0].quality.source_ref == "https://supplier.example/mug"


def test_crawl4ai_prefers_structured_extraction(monkeypatch):
    class Result:
        extracted_content = '[{"name": "Travel Mug", "price": 19.95}]'
        markdown = "unstructured fallback"

    class Crawler:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_args):
            return None
        async def arun(self, **_kwargs):
            return Result()

    monkeypatch.setitem(sys.modules, "crawl4ai", types.SimpleNamespace(AsyncWebCrawler=Crawler))
    adapter = Crawl4AIResearchAdapter(allowed_domains={"supplier.example"}, respect_robots=False)
    records = pytest.importorskip("asyncio").run(
        adapter.discover("https://supplier.example/item", context=SidecarContext(dry_run=False, approval_state="approved"))
    )
    assert records[0]["name"] == "Travel Mug"
    assert records[0]["quality"]["provenance"] == "live"
