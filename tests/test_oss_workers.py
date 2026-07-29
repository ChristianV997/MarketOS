import pytest

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


def test_crawl4ai_rejects_non_allowlisted_live_domain():
    adapter = Crawl4AIResearchAdapter(allowed_domains={"example.com"})
    with pytest.raises(PermissionError):
        pytest.importorskip("asyncio").run(
            adapter.discover("https://evil.example/test", context=SidecarContext(dry_run=False))
        )
