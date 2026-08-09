"""Tests for backend.creation and backend.launch — listings, store pages, campaigns."""
from backend.creation.creative_generator import generate_listing, generate_ad_copy
from backend.creation.store_builder import create_product_page, build_product, update_product_page
from backend.launch.orchestrator import launch_product
from backend.integrations import meta_ads_client


# ── creative generation (offline → template fallback) ─────────────────────────

def test_listing_fallback_shape():
    listing = generate_listing("Test Widget", 49.99)
    assert listing["title"]
    assert len(listing["title"]) <= 70
    assert len(listing["bullets"]) == 5
    assert "49.99" in listing["description"]


def test_ad_copy_fallback_shape():
    copy = generate_ad_copy("Test Widget", "tiktok")
    assert copy["platform"] == "tiktok"
    assert 1 <= len(copy["hooks"]) <= 5
    assert len(copy["headlines"]) == 3
    assert all(len(h) <= 40 for h in copy["headlines"])
    assert len(copy["ctas"]) == 3


# ── store builder (dry-run) ───────────────────────────────────────────────────

def test_create_product_page_dry_run():
    page = create_product_page("Test Widget", "<p>desc</p>", 49.99)
    assert page["status"] == "ok"
    assert page["dry_run"] is True
    assert page["product_id"].startswith("dryprod_")


def test_dry_run_page_ids_unique():
    a = create_product_page("Same Title", "<p>d</p>", 10.0)
    b = create_product_page("Same Title", "<p>d</p>", 10.0)
    assert a["product_id"] != b["product_id"]


def test_update_product_page_dry_run():
    page = create_product_page("Test Widget", "<p>d</p>", 49.99)
    result = update_product_page(page["product_id"], price=39.99, status="paused")
    assert result["status"] == "ok"
    assert result["dry_run"] is True
    assert result["product_id"] == page["product_id"]


def _green_verdict(product="Test Widget"):
    return {
        "product": product,
        "confidence": 0.8,
        "recommendation": "green",
        "ready_for_creation": True,
        "risk_flags": [],
        "retail_price": 39.99,
        "suggested_price": 39.99,
        "margin": {"margin_status": "profitable"},
        "supplier": {"supplier": "cj_dropshipping", "product_id": "cj_123",
                     "fulfillment_days": 8},
    }


def test_build_product_green_path():
    build = build_product(_green_verdict())
    assert build["status"] == "ok"
    assert build["page"]["status"] == "ok"
    assert "tiktok" in build["ad_copy"] and "meta" in build["ad_copy"]
    assert build["listing"]["title"]


def test_build_product_skips_unvalidated():
    verdict = _green_verdict()
    verdict["ready_for_creation"] = False
    build = build_product(verdict)
    assert build["status"] == "skipped"


# ── meta campaign creation (dry-run) ──────────────────────────────────────────

def test_meta_create_campaign_dry_run():
    cid = meta_ads_client.create_campaign("test_campaign", daily_budget=25.0)
    assert cid.startswith("dry_meta")


def test_meta_dry_ids_unique():
    a = meta_ads_client.create_campaign("c1")
    b = meta_ads_client.create_campaign("c2")
    assert a != b


def test_meta_full_hierarchy():
    cid = meta_ads_client.create_campaign("c")
    asid = meta_ads_client.create_ad_set(cid, "as", daily_budget=20.0)
    ad = meta_ads_client.create_ad(asid, "ad", headline="H", body="B", link_url="u")
    assert cid and asid and ad


# ── launch orchestration ──────────────────────────────────────────────────────

def test_launch_product_both_platforms():
    build = build_product(_green_verdict())
    result = launch_product(build, budget_daily=50.0, platforms=("tiktok", "meta"))
    assert result["status"] == "ok"
    assert result["live_count"] == 2
    platforms = {c["platform"] for c in result["campaigns"]}
    assert platforms == {"tiktok", "meta"}
    for c in result["campaigns"]:
        assert c["status"] == "live"
        assert len(c["ad_ids"]) >= 1
        assert c["budget"] > 0


def test_launch_budget_split_sums_to_daily():
    build = build_product(_green_verdict())
    result = launch_product(build, budget_daily=100.0, platforms=("tiktok", "meta"))
    assert abs(result["total_budget"] - 100.0) < 0.05


def test_launch_single_platform():
    build = build_product(_green_verdict())
    result = launch_product(build, budget_daily=30.0, platforms=("tiktok",))
    assert result["live_count"] == 1
    assert result["campaigns"][0]["platform"] == "tiktok"
    assert abs(result["campaigns"][0]["budget"] - 30.0) < 0.05


def test_launch_platform_failure_isolated(monkeypatch):
    # TikTok campaign creation failing must not block the Meta launch
    from backend.integrations import tiktok_ads
    monkeypatch.setattr(tiktok_ads, "create_campaign", lambda **kw: "")
    build = build_product(_green_verdict())
    result = launch_product(build, budget_daily=50.0, platforms=("tiktok", "meta"))
    by_platform = {c["platform"]: c for c in result["campaigns"]}
    assert by_platform["tiktok"]["status"] == "error"
    assert by_platform["meta"]["status"] == "live"
    assert result["status"] == "ok"   # one live platform is still a success


class TestLaunchProductRiskGate:
    """Tier 2 fix: a real (non-dry-run) launch consults backend.risk.gate
    before ever calling the platform — a kill switch or exhausted daily cap
    must block it with zero platform API calls, not just fail silently
    after the fact."""

    def test_dry_run_never_touches_the_risk_gate(self, monkeypatch):
        # The default (dry-run) path is the overwhelming common case in
        # tests/dev — it must be completely unaffected by the risk gate.
        calls = []
        monkeypatch.setattr("backend.risk.gate.check_spend",
                           lambda amount: calls.append(amount) or {"allowed": True, "adjusted_amount": amount})
        build = build_product(_green_verdict())
        result = launch_product(build, budget_daily=50.0, platforms=("tiktok",))
        assert result["status"] == "ok"
        assert calls == []  # never consulted — dry-run isn't real spend

    def test_kill_switch_blocks_live_launch_before_any_platform_call(self, monkeypatch):
        import backend.launch.orchestrator as orch_mod
        monkeypatch.setattr(orch_mod, "_platform_is_live", lambda platform: True)

        platform_calls = []
        monkeypatch.setattr("backend.integrations.tiktok_ads.create_campaign",
                           lambda **kw: platform_calls.append(kw) or "should_not_be_called")

        from backend.risk.gate import _engine
        _engine().activate_kill_switch(reason="test")
        try:
            build = build_product(_green_verdict())
            result = launch_product(build, budget_daily=50.0, platforms=("tiktok",))
        finally:
            _engine().deactivate_kill_switch()

        assert platform_calls == []  # blocked before the platform was ever touched
        assert result["campaigns"][0]["status"] == "error"
        assert "risk_gate_blocked" in result["campaigns"][0]["error"]
