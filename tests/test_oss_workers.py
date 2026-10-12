import time
import pytest

from backend.adapters.research.crawl4ai import Crawl4AIResearchAdapter
from backend.contracts.adapters import SidecarContext
from backend.integrations.browser_use_worker import BrowserUseWorker, RemoteBrowserUseWorker, _history_trace, build_remote_browser_use_runner


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


def test_remote_browser_worker_requires_private_token_and_valid_url():
    with pytest.raises(ValueError, match="TOKEN"):
        build_remote_browser_use_runner("http://browser-use-worker:8001", token="")
    with pytest.raises(ValueError, match="without embedded credentials"):
        build_remote_browser_use_runner("https://token@example.test", token="secret")


def test_remote_browser_worker_health_probes_the_isolated_service(monkeypatch):
    class Response:
        is_success = True
        status_code = 200

        def json(self):
            return {"ready": True}

    monkeypatch.setattr("httpx.get", lambda *_args, **_kwargs: Response())
    health = RemoteBrowserUseWorker("http://browser-use-worker:8001", "worker-secret").health()
    assert health.configured is True
    assert health.reachable is True
    assert health.detail == "remote browser worker ready"


def test_browser_worker_rejects_non_allowlisted_domain():
    worker = BrowserUseWorker(allowed_domains={"supplier.example"})
    with pytest.raises(PermissionError):
        pytest.importorskip("asyncio").run(
            worker.execute("supplier_research", {"url": "https://other.example/item"}, context=SidecarContext(dry_run=True))
        )


def test_browser_worker_requires_trace_for_live_runner():
    async def runner(_workflow, _payload, _context):
        return {"status": "done"}
    worker = BrowserUseWorker(runner=runner, allowed_domains={"supplier.example"})
    with pytest.raises(RuntimeError, match="execution trace"):
        pytest.importorskip("asyncio").run(
            worker.execute(
                "supplier_research", {"url": "https://supplier.example/product"},
                context=SidecarContext(dry_run=False, approval_state="approved", idempotency_key="research-1"),
            )
        )


def test_browser_worker_live_execution_requires_allowlist_url_approval_and_idempotency():
    async def runner(_workflow, _payload, _context):
        return {"trace_id": "trace-1"}

    worker = BrowserUseWorker(runner=runner)
    with pytest.raises(PermissionError, match="ALLOWED_DOMAINS"):
        pytest.importorskip("asyncio").run(
            worker.execute("supplier_research", {"url": "https://supplier.example/product"}, context=SidecarContext(dry_run=False, approval_state="approved", idempotency_key="research-1"))
        )

    worker = BrowserUseWorker(runner=runner, allowed_domains={"supplier.example"})
    with pytest.raises(PermissionError, match="approval"):
        pytest.importorskip("asyncio").run(
            worker.execute("supplier_research", {"url": "https://supplier.example/product"}, context=SidecarContext(dry_run=False, idempotency_key="research-1"))
        )
    with pytest.raises(ValueError, match="idempotency_key"):
        pytest.importorskip("asyncio").run(
            worker.execute("supplier_research", {"url": "https://supplier.example/product"}, context=SidecarContext(dry_run=False, approval_state="approved"))
        )


def test_browser_worker_enforces_runner_action_count():
    async def runner(_workflow, _payload, _context):
        return {"trace_id": "trace-1", "trace": {"steps": []}, "action_count": 3}

    worker = BrowserUseWorker(runner=runner, allowed_domains={"supplier.example"}, max_actions=2)
    with pytest.raises(RuntimeError, match="action limit"):
        pytest.importorskip("asyncio").run(
            worker.execute(
                "supplier_research", {"url": "https://supplier.example/product"},
                context=SidecarContext(dry_run=False, approval_state="approved", idempotency_key="research-1"),
            )
        )


def test_browser_history_trace_is_bounded_and_redacts_sensitive_page_state():
    class History:
        history = [
            {"action": "click", "cookie": "private", "screenshot": "data:image/png;base64,large"},
            {"action": "extract", "result": "useful"},
        ]

    trace = _history_trace(History())
    assert trace["action_count"] == 2
    assert trace["steps"][0]["cookie"] == "<redacted>"
    assert trace["steps"][0]["screenshot"] == "<screenshot captured>"




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
        {
            "name": "Travel Mug", "url": "https://supplier.example/mug", "price": "19.95",
            "currency": "USD", "fetched_at": 1_700_000_000.0, "retrieval_mode": "fresh_fetch",
            "quality": {"provenance": "live"},
        },
        {"content": "not a product"},
    ])
    assert len(candidates) == 1
    assert candidates[0].name == "Travel Mug"
    assert candidates[0].selling_price == 19.95
    assert candidates[0].quality.source_ref == "https://supplier.example/mug"
    assert candidates[0].quality.provenance == "public_page"
    assert candidates[0].quality.observed_at.timestamp() == 1_700_000_000.0


def test_crawl4ai_extracts_only_explicit_jsonld_product_evidence():
    html = '''
      <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"Product","name":"Travel Mug","sku":"mug-blue",
         "offers":{"@type":"Offer","price":"19.95","priceCurrency":"usd","availability":"https://schema.org/InStock"}}
      </script>
      <script type="application/ld+json">{"@type":"Organization","name":"Not a product"}</script>
    '''
    records = Crawl4AIResearchAdapter._product_records_from_jsonld(html, "https://supplier.example/mug")
    assert len(records) == 1
    assert records[0]["product_id"] == "mug-blue"
    assert records[0]["selling_price"] == 19.95
    assert records[0]["currency"] == "USD"
    assert records[0]["quality"]["attribution"] == "attributed"


def test_crawl4ai_rejects_unnamed_structured_records():
    records = Crawl4AIResearchAdapter._normalized_structured_records(
        [{"price": 20}, {"product_name": "Travel Mug", "price": 20}], "https://supplier.example/mug"
    )
    assert len(records) == 1
    assert records[0]["name"] == "Travel Mug"


def test_crawl4ai_raw_page_cache_is_separate_from_dry_run_and_reextracts_products():
    adapter = Crawl4AIResearchAdapter()
    url = "https://supplier.example/mug"
    adapter._raw_cache_put(url, {
        "html": '<script type="application/ld+json">{"@type":"Product","name":"Travel Mug","sku":"mug-1"}</script>',
    }, dry_run=False)
    assert adapter._raw_cache_get(url, dry_run=True) is None
    raw = adapter._raw_cache_get(url, dry_run=False)
    assert raw is not None
    records = adapter._records_from_raw(raw, url)
    assert records[0]["product_id"] == "mug-1"


def test_crawl4ai_supplier_offers_require_an_explicit_cost_not_selling_price():
    offers = Crawl4AIResearchAdapter.normalize_supplier_offers([
        {"product_id": "mug-blue", "price": 19.95, "url": "https://supplier.example/mug"},
        {
            "product_id": "mug-blue", "unit_cost": 6.5, "shipping_cost": 2, "inventory_units": 25,
            "currency": "USD", "shipping_currency": "USD", "fetched_at": 1_700_000_000.0,
            "retrieval_mode": "fresh_fetch", "url": "https://supplier.example/mug",
        },
    ])
    assert len(offers) == 1
    assert offers[0].unit_cost == 6.5
    assert offers[0].shipping_cost == 2.0
    assert offers[0].supplier_id == "supplier.example"
    assert offers[0].quality.provenance == "public_page"
    assert offers[0].quality.observed_at.timestamp() == 1_700_000_000.0


def test_crawl4ai_jsonld_extraction_adversarial_redos_witness_is_bounded():
    """Verify CodeQL alert #932 witness runs in bounded linear time without ReDoS."""
    adversarial_html = (
        '<script=type="application/ld+json">'
        + '<script=type="application/ld+json">a' * 2500
        + '<script type="application/ld+json">'
        + '{"@context": "https://schema.org", "@type": "Product", "name": "Resilient Mug", "sku": "res-1", "offers": {"price": "12.50"}}'
        + '</script>'
    )
    t0 = time.perf_counter()
    records = Crawl4AIResearchAdapter._product_records_from_jsonld(adversarial_html, "https://supplier.example/resilient")
    elapsed = time.perf_counter() - t0

    assert elapsed < 1.0, f"Extraction took too long ({elapsed:.3f}s), possible polynomial backtracking"
    assert len(records) == 1
    assert records[0]["name"] == "Resilient Mug"
    assert records[0]["selling_price"] == 12.50


def test_crawl4ai_jsonld_extraction_adversarial_unclosed_and_nested_scripts():
    """Verify parser handles unclosed script tags and malformed HTML gracefully."""
    # 1. Unclosed script tag running to EOF completes safely without crashing or hanging
    unclosed_eof_html = (
        '<script type="application/ld+json">' * 1000
        + '{"incomplete": "no closing tag"}'
    )
    t0 = time.perf_counter()
    records_unclosed = Crawl4AIResearchAdapter._product_records_from_jsonld(unclosed_eof_html, "https://supplier.example/unclosed")
    elapsed_unclosed = time.perf_counter() - t0
    assert elapsed_unclosed < 1.0
    assert records_unclosed == []

    # 2. Malformed script block followed by valid Product JSON-LD extracts the valid record
    malformed_and_valid_html = (
        '<script type="application/ld+json">{"broken": json without closing brace</script>'
        + '<script type="application/ld+json"></script>' * 500
        + '<script type="application/ld+json">{"@type": "Product", "name": "Valid Mug", "offers": {"price": "9.99"}}</script>'
    )
    t1 = time.perf_counter()
    records = Crawl4AIResearchAdapter._product_records_from_jsonld(malformed_and_valid_html, "https://supplier.example/valid")
    elapsed = time.perf_counter() - t1
    assert elapsed < 1.0
    assert len(records) == 1
    assert records[0]["name"] == "Valid Mug"
    assert records[0]["selling_price"] == 9.99


def test_crawl4ai_jsonld_extraction_supports_cdata_and_comment_wrappers():
    """Verify JSON-LD scripts wrapped in CDATA or HTML comments are extracted cleanly."""
    cdata_html = """
    <script type="application/ld+json">
    /*<![CDATA[*/
    {"@context": "https://schema.org", "@type": "Product", "name": "CDATA Product", "sku": "cd-1", "offers": {"price": "25.00"}}
    /*]]>*/
    </script>
    <script type="application/ld+json">
    <!--
    {"@context": "https://schema.org", "@type": "Product", "name": "Comment Product", "sku": "cm-1", "offers": {"price": "30.00"}}
    -->
    </script>
    """
    records = Crawl4AIResearchAdapter._product_records_from_jsonld(cdata_html, "https://supplier.example/wrappers")
    assert len(records) == 2
    names = {r["name"] for r in records}
    assert names == {"CDATA Product", "Comment Product"}


def test_crawl4ai_jsonld_extraction_supports_varied_attribute_formats_and_graph():
    """Verify JSON-LD extraction handles case variations, MIME params, and @graph hierarchies."""
    complex_html = """
    <script TYPE="APPLICATION/LD+JSON; CHARSET=UTF-8" id="schema-graph">
    {
      "@context": "https://schema.org",
      "@graph": [
        {"@type": "Organization", "name": "Supplier Inc"},
        {"@type": "Product", "name": "Graph Product 1", "sku": "gp-1", "offers": {"price": "10.00", "priceCurrency": "EUR"}},
        {"@type": ["Product", "SomeOtherType"], "name": "Graph Product 2", "sku": "gp-2", "offers": {"price": "20.00"}}
      ]
    }
    </script>
    <script type='application/ld+json' async>
    {"@type": "Product", "name": "Single Quote Product", "sku": "sq-1", "offers": {"price": "5.00"}}
    </script>
    <script type="application/ld+json">
    {malformed json}
    </script>
    """
    records = Crawl4AIResearchAdapter._product_records_from_jsonld(complex_html, "https://supplier.example/complex")
    assert len(records) == 3
    sku_to_record = {r["product_id"]: r for r in records}
    assert "gp-1" in sku_to_record
    assert sku_to_record["gp-1"]["selling_price"] == 10.00
    assert sku_to_record["gp-1"]["currency"] == "EUR"
    assert "gp-2" in sku_to_record
    assert sku_to_record["gp-2"]["selling_price"] == 20.00
    assert "sq-1" in sku_to_record
    assert sku_to_record["sq-1"]["selling_price"] == 5.00


def test_crawl4ai_jsonld_extraction_deduplicates_by_product_id_and_name():
    """Verify duplicate products within the same page are deduplicated deterministically."""
    html = """
    <script type="application/ld+json">
    {"@type": "Product", "name": "Travel Mug", "sku": "mug-1", "offers": {"price": "10.00"}}
    </script>
    <script type="application/ld+json">
    {"@type": "Product", "name": "travel mug", "sku": "mug-1", "offers": {"price": "12.00"}}
    </script>
    """
    records = Crawl4AIResearchAdapter._product_records_from_jsonld(html, "https://supplier.example/dedupe")
    assert len(records) == 1
    assert records[0]["selling_price"] == 10.00


def test_crawl4ai_jsonld_extraction_empty_and_whitespace_input():
    """Verify empty, whitespace, and non-string inputs fail gracefully returning empty list."""
    for empty_val in ("", "   \n\t  ", None, 12345, [], {}):
        records = Crawl4AIResearchAdapter._product_records_from_jsonld(empty_val, "https://supplier.example/empty")
        assert records == []


def test_crawl4ai_jsonld_extraction_escaped_html_entities_and_bom():
    """Verify HTML entities and byte-order-marks in JSON-LD are handled cleanly."""
    # 1. HTML-escaped JSON (common in legacy CMS and CMS templates)
    escaped_html = """
    <script type="application/ld+json">
    {&quot;@context&quot;: &quot;https://schema.org&quot;, &quot;@type&quot;: &quot;Product&quot;, &quot;name&quot;: &quot;Escaped &amp; Sanitized Mug&quot;, &quot;sku&quot;: &quot;esc-1&quot;, &quot;offers&quot;: {&quot;price&quot;: &quot;18.50&quot;}}
    </script>
    """
    records = Crawl4AIResearchAdapter._product_records_from_jsonld(escaped_html, "https://supplier.example/escaped")
    assert len(records) == 1
    assert records[0]["name"] == "Escaped & Sanitized Mug"
    assert records[0]["selling_price"] == 18.50

    # 2. Leading BOM and JavaScript-commented CDATA wrapper
    bom_cdata_html = """
    <script type="application/ld+json">
    \ufeff//<![CDATA[
    {"@context": "https://schema.org", "@type": "Product", "name": "BOM CDATA Mug", "sku": "bom-1", "offers": {"price": "22.00"}}
    //]]>
    </script>
    """
    records_bom = Crawl4AIResearchAdapter._product_records_from_jsonld(bom_cdata_html, "https://supplier.example/bom")
    assert len(records_bom) == 1
    assert records_bom[0]["name"] == "BOM CDATA Mug"
    assert records_bom[0]["selling_price"] == 22.00


def test_crawl4ai_jsonld_extraction_unrelated_scripts_and_styles_not_misclassified():
    """Confirm unrelated script, style, comment, and arbitrary HTML are not misclassified as JSON-LD."""
    unrelated_html = """
    <html>
      <head>
        <style>
          .product { content: 'application/ld+json'; }
        </style>
        <script type="text/javascript">
          var schema = {"@type": "Product", "name": "JS Object Not JSONLD", "offers": {"price": "99.99"}};
        </script>
        <script>
          // Untyped script tag defaults to JavaScript
          var untyped = {"@type": "Product", "name": "Untyped Script Product"};
        </script>
        <!--
        <script type="application/ld+json">
          {"@type": "Product", "name": "Commented Out Product", "offers": {"price": "1.00"}}
        </script>
        -->
        <template>
          <div data-type="application/ld+json">Template content</div>
        </template>
      </head>
      <body>
        <p>Mention of &lt;script type="application/ld+json"&gt; in plain text body</p>
        <script type="application/ld+json">
          {"@type": "Product", "name": "Legitimate Product", "offers": {"price": "14.99"}}
        </script>
      </body>
    </html>
    """
    records = Crawl4AIResearchAdapter._product_records_from_jsonld(unrelated_html, "https://supplier.example/unrelated")
    assert len(records) == 1
    assert records[0]["name"] == "Legitimate Product"
    assert records[0]["selling_price"] == 14.99


def test_crawl4ai_jsonld_extraction_bounded_large_input_and_script_limits():
    """Verify bounded resource consumption on massive inputs and script element counts."""
    # 1. Very large HTML document (> 2.5MB) is bounded and processes without error or hang
    large_prefix = "<p>" + ("padding content " * 200_000) + "</p>"  # ~3.2MB
    large_html = (
        '<script type="application/ld+json">'
        + '{"@type": "Product", "name": "Early Product", "offers": {"price": "10.00"}}'
        + '</script>'
        + large_prefix
    )
    t0 = time.perf_counter()
    records = Crawl4AIResearchAdapter._product_records_from_jsonld(large_html, "https://supplier.example/large")
    elapsed = time.perf_counter() - t0
    assert elapsed < 1.0
    assert len(records) == 1
    assert records[0]["name"] == "Early Product"


    # 2. Excessive count of JSON-LD scripts is bounded to MAX_EXTRACTED_SCRIPTS (100)
    many_scripts_html = "".join(
        f'<script type="application/ld+json">{{"@type": "Product", "name": "Product {i}", "sku": "p-{i}", "offers": {{"price": "10.00"}}}}</script>'
        for i in range(150)
    )
    records_many = Crawl4AIResearchAdapter._product_records_from_jsonld(many_scripts_html, "https://supplier.example/many")
    assert len(records_many) == 100
