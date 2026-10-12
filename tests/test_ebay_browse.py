from __future__ import annotations

import pytest

from backend.adapters.research.ebay_browse import (
    EbayBrowseAdapter,
    EbayBrowseConfig,
    EbayBrowseRequest,
    MAX_PAGE_SIZE,
    brief_query,
)
from evaluation.commerce.opportunity_synthesis import build_product_opportunity_synthesis


def config(**overrides):
    values = {"credential_ref": "credential-ebay-browse", "allow_network": True, "approval_granted": True}
    values.update(overrides)
    return EbayBrowseConfig(**values)


def response(*items):
    return {"itemSummaries": list(items)}


def item(item_id="v1", *, price=True, url=True):
    value = {
        "itemId": item_id,
        "title": "Portable espresso maker",
        "estimatedAvailabilityStatus": "IN_STOCK",
        "localizedAspects": [{"name": "Color", "value": "Black"}],
    }
    if price:
        value["price"] = {"value": "32.50", "currency": "USD"}
        value["shippingOptions"] = [{"shippingCost": {"value": "4.00", "currency": "USD"}}]
    if url:
        value["itemWebUrl"] = f"https://www.ebay.com/itm/{item_id}"
    return value


def test_brief_to_query_is_bounded_and_uses_existing_brief_fields():
    brief = {"candidate_id": "espresso-1", "product_query": "portable espresso maker", "category": "kitchen", "target_market": "US", "language": "en"}
    assert brief_query(brief) == "portable espresso maker kitchen US en"


def test_disabled_and_unconfigured_states_do_not_invoke_transport():
    calls = []
    transport = lambda request, *, timeout_s: calls.append(request)  # noqa: ARG005
    brief = {"candidate_id": "espresso-1", "query": "portable espresso maker"}
    assert EbayBrowseAdapter(EbayBrowseConfig(enabled=False), transport=transport).search_brief(brief).status == "disabled"
    assert EbayBrowseAdapter(EbayBrowseConfig(), transport=transport).search_brief(brief).status == "unconfigured"
    assert calls == []


def test_injected_transport_normalizes_current_listing_and_deduplicates():
    requests: list[EbayBrowseRequest] = []

    def transport(request, *, timeout_s):
        assert timeout_s == 10.0
        requests.append(request)
        return response(item("v1"), item("v1"), item("v2", price=False, url=False))

    result = EbayBrowseAdapter(config(), transport=transport).search_brief(
        {"candidate_id": "espresso-1", "query": "portable espresso maker"}
    )
    assert result.status == "ok"
    assert len(result.listings) == 2
    assert [listing.item_id for listing in result.listings] == ["v1", "v2"]
    first = result.listings[0]
    assert first.price == 32.5
    assert first.shipping_cost == 4.0
    assert first.variants == ({"name": "Color", "value": "Black"},)
    assert result.listings[1].price is None
    assert "price" not in result.listings[1].field_provenance
    assert result.evidence[0].source_type == "ebay_public_listing_snapshot"
    assert result.evidence[0].evidence_mode == "live_readonly"
    assert result.evidence[0].best_seller_badge is False
    assert "current_listing_not_sales_or_demand_proof" in result.evidence[0].warnings
    assert requests[0].path == "/buy/browse/v1/item_summary/search"
    assert requests[0].params["q"] == "portable espresso maker"
    assert requests[0].params["limit"] == "20"


def test_normalized_report_is_consumable_by_existing_synthesis_without_new_scorer():
    result = EbayBrowseAdapter(config(), transport=lambda request, *, timeout_s: response(item())).search_brief(
        {"candidate_id": "espresso-1", "query": "portable espresso maker"}
    )
    report = build_product_opportunity_synthesis(result.marketplace_report(), None, None).to_dict()
    assert report["top_candidate_id"] == "espresso-1"
    assert report["source_reports"]["marketplace"] == "supplied"
    assert report["candidates"][0]["evidence_matrix"]["marketplace"]["status"] == "supplied"
    assert report["overall_recommendation"] == "validate_supplier_first"


def test_auth_timeout_malformed_and_no_mock_evidence_on_failure():
    brief = {"candidate_id": "espresso-1", "query": "espresso maker"}
    auth = EbayBrowseAdapter(config(), transport=lambda request, *, timeout_s: (_ for _ in ()).throw(PermissionError()))
    timeout = EbayBrowseAdapter(config(), transport=lambda request, *, timeout_s: (_ for _ in ()).throw(TimeoutError()))
    malformed = EbayBrowseAdapter(config(), transport=lambda request, *, timeout_s: {"itemSummaries": {}})
    for adapter, expected in ((auth, "auth_failed"), (timeout, "timeout"), (malformed, "malformed_response")):
        result = adapter.search_brief(brief)
        assert result.status == expected
        assert result.listings == ()
        assert result.evidence == ()
        assert result.marketplace_report()["candidate_count"] == 0
        assert result.network_calls is True


def test_pagination_is_capped_and_duplicate_ids_remain_unique():
    calls = []

    def transport(request, *, timeout_s):
        calls.append(request)
        return response(item(f"id-{request.params['offset']}"))

    result = EbayBrowseAdapter(config(page_size=1, max_pages=2), transport=transport).search_brief(
        {"candidate_id": "espresso-1", "query": "espresso maker"}
    )
    assert result.status == "ok"
    assert result.pages_attempted == 2
    assert len(calls) == 2
    assert [call.params["offset"] for call in calls] == ["0", "1"]
    assert "pagination_cap_reached" in result.warnings
    assert len({listing.item_id for listing in result.listings}) == len(result.listings)


def test_config_rejects_unbounded_settings():
    with pytest.raises(ValueError):
        EbayBrowseConfig(page_size=MAX_PAGE_SIZE + 1)  # noqa: F821
