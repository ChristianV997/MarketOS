"""Tests for backend.validation — margin math, suppliers, validator verdicts."""
import pytest

from backend.validation.margin_calculator import calculate_margin, suggest_retail_price
from backend.validation.suppliers import (
    SupplierQuote, quote_all, find_best_supplier, _MIN_RELIABILITY,
)
from backend.validation.validator import validate_product


# ── margin calculator ─────────────────────────────────────────────────────────

def test_high_margin_product_is_profitable():
    m = calculate_margin(supplier_cost=10.0, retail_price=60.0, shipping_cost=2.0)
    assert m["margin_status"] == "profitable"
    assert m["net_margin_pct"] > 15
    assert m["landed_cost"] == 12.0


def test_thin_margin_product_is_loss():
    m = calculate_margin(supplier_cost=20.0, retail_price=24.0, shipping_cost=3.0)
    assert m["margin_status"] == "loss"


def test_zero_price_never_raises():
    m = calculate_margin(supplier_cost=10.0, retail_price=0.0)
    assert m["margin_status"] == "loss"
    assert m["net_margin_pct"] == 0.0


def test_negative_price_never_raises():
    m = calculate_margin(supplier_cost=10.0, retail_price=-5.0)
    assert m["margin_status"] == "loss"


def test_return_rate_reduces_net_margin():
    low  = calculate_margin(10.0, 50.0, return_rate=0.05)
    high = calculate_margin(10.0, 50.0, return_rate=0.30)
    assert high["net_margin"] < low["net_margin"]


def test_margin_fields_complete():
    m = calculate_margin(10.0, 50.0)
    for key in ("landed_cost", "gross_margin", "payment_fee", "platform_fee",
                "return_loss", "cac", "net_margin", "net_margin_pct", "margin_status"):
        assert key in m


def test_suggest_retail_price_hits_target():
    price = suggest_retail_price(15.0, target_net_margin_pct=20.0)
    m = calculate_margin(supplier_cost=15.0, retail_price=price)
    assert m["net_margin_pct"] >= 19.0   # bisection converges within a point


def test_suggest_retail_price_zero_cost():
    assert suggest_retail_price(0.0) == 0.0


# ── suppliers ─────────────────────────────────────────────────────────────────

def test_quote_all_returns_all_suppliers():
    quotes = quote_all("Test Widget")
    names = {q.supplier for q in quotes}
    assert names == {"cj_dropshipping", "zendrop", "spocket", "printful", "autods"}


def test_quotes_are_deterministic():
    a = find_best_supplier("Test Widget")
    b = find_best_supplier("Test Widget")
    assert a.supplier == b.supplier
    assert a.landed_cost == b.landed_cost


def test_best_supplier_is_cheapest_reliable():
    quotes = quote_all("Test Widget")
    best = find_best_supplier("Test Widget")
    reliable = [q for q in quotes if q.reliability >= _MIN_RELIABILITY]
    assert best.landed_cost == min(q.landed_cost for q in reliable)


def test_landed_cost_property():
    q = SupplierQuote("s", "id", "p", cost=10.0, shipping=2.5,
                      fulfillment_days=7, reliability=0.9)
    assert q.landed_cost == 12.5
    assert q.to_dict()["landed_cost"] == 12.5


def test_autods_dry_run_quote_is_deterministic():
    from backend.validation.suppliers import AutoDSClient
    client = AutoDSClient()
    a = client.quote("Test Widget")
    b = client.quote("Test Widget")
    assert a.supplier == "autods"
    assert a.landed_cost == b.landed_cost


def test_autods_live_quote_parses_response(monkeypatch):
    from backend.validation.suppliers import AutoDSClient
    monkeypatch.setenv("AUTODS_API_KEY", "fake-key")
    client = AutoDSClient()

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"products": [{
                "id": "ad_123", "cost": 7.5, "shipping_cost": 2.25, "processing_days": 8,
            }]}

    monkeypatch.setattr(
        "requests.get", lambda url, headers=None, params=None, timeout=None: FakeResponse(),
    )

    quote = client._live_quote("Test Widget")
    assert quote.product_id == "ad_123"
    assert quote.cost == 7.5
    assert quote.shipping == 2.25
    assert quote.fulfillment_days == 8


def test_autods_live_quote_returns_none_when_no_products(monkeypatch):
    from backend.validation.suppliers import AutoDSClient
    monkeypatch.setenv("AUTODS_API_KEY", "fake-key")
    client = AutoDSClient()

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"products": []}

    monkeypatch.setattr(
        "requests.get", lambda url, headers=None, params=None, timeout=None: FakeResponse(),
    )

    assert client._live_quote("Test Widget") is None


# ── validator ─────────────────────────────────────────────────────────────────

def test_validate_product_structure():
    v = validate_product("Test Widget")
    for key in ("product", "confidence", "recommendation", "ready_for_creation",
                "risk_flags", "margin", "competition", "supplier",
                "suggested_price", "retail_price"):
        assert key in v
    assert 0.0 <= v["confidence"] <= 1.0
    assert v["recommendation"] in ("green", "yellow", "red")


def test_validate_no_supplier_is_red(monkeypatch):
    monkeypatch.setattr("backend.validation.validator.find_best_supplier",
                        lambda name, category="general": None)
    v = validate_product("Ghost Product")
    assert v["recommendation"] == "red"
    assert v["ready_for_creation"] is False
    assert "no_supplier" in v["risk_flags"]


def test_validate_bad_margin_flags_risk():
    # Force a loss by pinning the retail price below landed cost
    quote = SupplierQuote("mock", "id", "Overpriced Widget", cost=30.0,
                          shipping=5.0, fulfillment_days=7, reliability=0.9)
    v = validate_product("Overpriced Widget", retail_price=20.0, supplier_quote=quote)
    assert "negative_margin" in v["risk_flags"]
    assert v["recommendation"] != "green"


def test_validate_slow_fulfillment_flagged():
    quote = SupplierQuote("mock", "id", "Slow Widget", cost=5.0,
                          shipping=1.0, fulfillment_days=21, reliability=0.9)
    v = validate_product("Slow Widget", supplier_quote=quote)
    assert "slow_fulfillment" in v["risk_flags"]
    assert v["ready_for_creation"] is False   # any risk flag blocks green


def test_validate_uses_suggested_price_when_none_given():
    v = validate_product("Test Widget")
    assert v["retail_price"] == v["suggested_price"]


def test_validate_product_includes_similar_past_products_field():
    v = validate_product("Test Widget")
    assert "similar_past_products" in v
    assert isinstance(v["similar_past_products"], list)


def test_validate_flags_repeated_similar_failures(monkeypatch):
    monkeypatch.setattr(
        "backend.validation.validator._find_similar_past_products",
        lambda name, top_k=3: [
            {"product": "Ghost Widget A", "similarity": 0.91, "confidence": 0.1, "recommendation": "red"},
            {"product": "Ghost Widget B", "similarity": 0.83, "confidence": 0.2, "recommendation": "red"},
        ],
    )
    v = validate_product("Test Widget")
    assert "similar_to_repeated_past_failures" in v["risk_flags"]
    assert v["ready_for_creation"] is False


def test_validate_no_flag_when_similar_products_not_mostly_red(monkeypatch):
    monkeypatch.setattr(
        "backend.validation.validator._find_similar_past_products",
        lambda name, top_k=3: [
            {"product": "Winner Widget", "similarity": 0.9, "confidence": 0.8, "recommendation": "green"},
        ],
    )
    v = validate_product("Test Widget")
    assert "similar_to_repeated_past_failures" not in v["risk_flags"]


def test_similar_past_products_lookup_never_raises(monkeypatch):
    from backend.validation.validator import _find_similar_past_products

    def _boom(*a, **kw):
        raise RuntimeError("vector store unreachable")

    monkeypatch.setattr("backend.vector.semantic_search.find_similar_products", _boom)
    assert _find_similar_past_products("Anything") == []


def test_index_validated_product_never_raises(monkeypatch):
    from backend.validation.validator import _index_validated_product

    def _boom(*a, **kw):
        raise RuntimeError("vector store unreachable")

    monkeypatch.setattr("backend.vector.embeddings.embed_text", _boom)
    # Should not raise even though embed_text is broken.
    _index_validated_product("Anything", {"confidence": 0.5, "recommendation": "yellow"}, "general")
