from __future__ import annotations

import io
from typing import Any

import pytest

from backend.adapters.research.ebay_browse import (
    EbayBrowseAdapter,
    EbayBrowseAuthorizationDecision,
    EbayBrowseConfig,
    EbayBrowseRateLimitError,
    EbayBrowseRequest,
    FixtureEbayBrowseTransport,
    LiveEbayBrowseTransport,
    MAX_PAGE_SIZE,
    MAX_RETRIES,
    SUPPORTED_MARKETPLACE_IDS,
    TRANSPORT_KIND_FIXTURE,
    TRANSPORT_KIND_LIVE,
    brief_query,
    evaluate_ebay_browse_authorization,
)
from evaluation.commerce.opportunity_synthesis import build_product_opportunity_synthesis


def config(**overrides):
    values = {"credential_ref": "credential-ebay-browse", "transport_kind": TRANSPORT_KIND_FIXTURE}
    values.update(overrides)
    return EbayBrowseConfig(**values)


def response(*items):
    return {"itemSummaries": list(items)}


def item(item_id="v1", *, price=True, url=True, currency="USD", marketplace_id=None):
    value: dict[str, Any] = {
        "itemId": item_id,
        "title": "Portable espresso maker",
        "estimatedAvailabilityStatus": "IN_STOCK",
        "localizedAspects": [{"name": "Color", "value": "Black"}],
    }
    if marketplace_id is not None:
        value["marketplaceId"] = marketplace_id
    if price:
        value["price"] = {"value": "32.50", "currency": currency}
        value["shippingOptions"] = [{"shippingCost": {"value": "4.00", "currency": currency or "USD"}}]
    if url:
        value["itemWebUrl"] = f"https://www.ebay.com/itm/{item_id}"
    return value


def test_brief_to_query_is_bounded_and_uses_existing_brief_fields():
    brief = {
        "candidate_id": "espresso-1",
        "product_query": "portable espresso maker",
        "category": "kitchen",
        "target_market": "US",
        "language": "en",
    }
    assert brief_query(brief) == "portable espresso maker kitchen US en"


def test_disabled_and_unconfigured_live_states_do_not_invoke_transport():
    calls = []

    def transport(request, *, timeout_s):  # noqa: ARG001
        calls.append(request)
        return response()

    transport.kind = TRANSPORT_KIND_LIVE
    brief = {"candidate_id": "espresso-1", "query": "portable espresso maker"}
    assert EbayBrowseAdapter(EbayBrowseConfig(enabled=False), transport=transport).search_brief(brief).status == "disabled"
    live = EbayBrowseAdapter(
        EbayBrowseConfig(credential_ref="", transport_kind=TRANSPORT_KIND_LIVE, allow_network=True),
        transport=transport,
    ).search_brief(brief)
    assert live.status == "unconfigured"
    assert calls == []


def test_fixture_transport_normalizes_listing_without_claiming_live():
    requests: list[EbayBrowseRequest] = []

    def transport(request, *, timeout_s):
        assert timeout_s == 10.0
        requests.append(request)
        return response(item("v1"), item("v1"), item("v2", price=False, url=False))

    transport.kind = TRANSPORT_KIND_FIXTURE
    result = EbayBrowseAdapter(config(), transport=transport).search_brief(
        {"candidate_id": "espresso-1", "query": "portable espresso maker"}
    )
    assert result.status == "ok"
    assert result.network_calls is False
    assert result.transport_kind == TRANSPORT_KIND_FIXTURE
    assert len(result.listings) == 2
    assert [listing.item_id for listing in result.listings] == ["v1", "v2"]
    first = result.listings[0]
    assert first.price == 32.5
    assert first.shipping_cost == 4.0
    assert first.marketplace_id == "EBAY_US"
    assert first.variants == ({"name": "Color", "value": "Black"},)
    assert result.listings[1].price is None
    assert "price" not in result.listings[1].field_provenance
    assert result.evidence[0].source_type == "ebay_public_listing_snapshot"
    assert result.evidence[0].evidence_mode == "fixture"
    assert result.evidence[0].site_id == "EBAY_US"
    assert result.evidence[0].source_confidence == 0.0
    assert result.evidence[0].network_calls is False
    assert result.evidence[0].best_seller_badge is False
    assert "current_listing_not_sales_or_demand_proof" in result.evidence[0].warnings
    assert "fixture_or_fake_transport_is_not_live_proof" in result.warnings
    assert result.marketplace_report()["evidence_mode"] == "fixture"
    assert result.marketplace_report()["network_calls"] is False
    assert requests[0].path == "/buy/browse/v1/item_summary/search"
    assert requests[0].params["q"] == "portable espresso maker"
    assert requests[0].params["limit"] == "20"


def test_missing_currency_stays_unknown_and_zero_price_is_retained():
    def transport(request, *, timeout_s):  # noqa: ARG001
        return response(
            {
                "itemId": "free-1",
                "title": "Free sample",
                "itemWebUrl": "https://www.ebay.com/itm/free-1",
                "price": {"value": "0", "currency": ""},
            },
            {
                "itemId": "no-currency",
                "title": "No currency",
                "itemWebUrl": "https://www.ebay.com/itm/no-currency",
                "price": {"value": "12.00"},
            },
        )

    transport.kind = TRANSPORT_KIND_FIXTURE
    result = EbayBrowseAdapter(config(), transport=transport).search_brief(
        {"candidate_id": "c1", "query": "sample"}
    )
    by_id = {listing.item_id: listing for listing in result.listings}
    assert by_id["free-1"].price == 0.0
    assert by_id["free-1"].currency == ""
    assert by_id["no-currency"].currency == ""
    assert by_id["no-currency"].field_provenance["currency"] == "unavailable"
    assert result.evidence[0].currency == ""
    assert result.evidence[1].currency == ""
    assert "USD" not in {item.currency for item in result.evidence}


def test_marketplace_is_validated_and_retained_with_mismatch_warning():
    with pytest.raises(ValueError):
        EbayBrowseConfig(credential_ref="c", marketplace_id="NOT_A_REAL_MARKET")
    assert "EBAY_DE" in SUPPORTED_MARKETPLACE_IDS

    def transport(request, *, timeout_s):  # noqa: ARG001
        assert request.marketplace_id == "EBAY_DE"
        return response(item("v1", marketplace_id="EBAY_US"))

    transport.kind = TRANSPORT_KIND_FIXTURE
    result = EbayBrowseAdapter(config(marketplace_id="EBAY_DE"), transport=transport).search_brief(
        {"candidate_id": "c1", "query": "espresso"}
    )
    assert result.status == "ok"
    assert result.marketplace_id == "EBAY_DE"
    assert result.listings[0].marketplace_id == "EBAY_DE"
    assert result.evidence[0].site_id == "EBAY_DE"
    assert "listing_marketplace_mismatch" in result.warnings


def test_approval_ledger_denies_live_network_despite_caller_flags():
    calls = []

    def transport(request, *, timeout_s):  # noqa: ARG001
        calls.append(request)
        return response(item())

    transport.kind = TRANSPORT_KIND_LIVE
    decision = evaluate_ebay_browse_authorization()
    assert decision.authorized is False
    assert decision.request_type == "provider_call"
    assert decision.can_be_approved_now is False

    result = EbayBrowseAdapter(
        config(transport_kind=TRANSPORT_KIND_LIVE, allow_network=True, authorization=decision),
        transport=transport,
    ).search_brief({"candidate_id": "espresso-1", "query": "espresso maker"})
    assert result.status == "approval_denied"
    assert result.network_calls is False
    assert result.listings == ()
    assert result.authorization is not None
    assert result.authorization.authorized is False
    assert calls == []
    # Caller cannot invent authorization by forging authorized=True.
    forged = EbayBrowseAuthorizationDecision(
        authorized=True,
        request_type="provider_call",
        simulation_result="forged",
        can_be_approved_now=True,
        blocking_reasons=(),
        missing_conditions=(),
        source="caller_override",
    )
    forged_result = EbayBrowseAdapter(
        config(transport_kind=TRANSPORT_KIND_LIVE, allow_network=True, authorization=forged),
        transport=transport,
    ).search_brief({"candidate_id": "espresso-1", "query": "espresso maker"})
    assert forged_result.status == "approval_denied"
    assert forged_result.authorization is not None
    assert forged_result.authorization.authorized is False
    assert calls == []


def test_normalized_report_is_consumable_by_existing_synthesis_without_new_scorer():
    transport = FixtureEbayBrowseTransport(response(item()))
    result = EbayBrowseAdapter(config(), transport=transport).search_brief(
        {"candidate_id": "espresso-1", "query": "portable espresso maker"}
    )
    report = build_product_opportunity_synthesis(result.marketplace_report(), None, None).to_dict()
    assert report["top_candidate_id"] == "espresso-1"
    assert report["source_reports"]["marketplace"] == "supplied"
    assert report["candidates"][0]["evidence_matrix"]["marketplace"]["status"] == "supplied"
    assert report["overall_recommendation"] == "validate_supplier_first"


def test_auth_timeout_rate_limit_malformed_and_no_mock_evidence_on_failure():
    brief = {"candidate_id": "espresso-1", "query": "espresso maker"}

    def auth_transport(request, *, timeout_s):  # noqa: ARG001
        raise PermissionError()

    def timeout_transport(request, *, timeout_s):  # noqa: ARG001
        raise TimeoutError()

    def rate_transport(request, *, timeout_s):  # noqa: ARG001
        raise EbayBrowseRateLimitError()

    def malformed_transport(request, *, timeout_s):  # noqa: ARG001
        return {"itemSummaries": {}}

    for fn in (auth_transport, timeout_transport, rate_transport, malformed_transport):
        fn.kind = TRANSPORT_KIND_FIXTURE

    cases = (
        (auth_transport, "auth_failed"),
        (timeout_transport, "timeout"),
        (rate_transport, "rate_limited"),
        (malformed_transport, "malformed_response"),
    )
    for transport, expected in cases:
        result = EbayBrowseAdapter(config(), transport=transport).search_brief(brief)
        assert result.status == expected
        assert result.listings == ()
        assert result.evidence == ()
        assert result.marketplace_report()["candidate_count"] == 0
        assert result.network_calls is False


def test_pagination_is_capped_and_duplicate_ids_remain_unique():
    calls = []

    def transport(request, *, timeout_s):  # noqa: ARG001
        calls.append(request)
        return response(item(f"id-{request.params['offset']}"))

    transport.kind = TRANSPORT_KIND_FIXTURE
    result = EbayBrowseAdapter(config(page_size=1, max_pages=2), transport=transport).search_brief(
        {"candidate_id": "espresso-1", "query": "espresso maker"}
    )
    assert result.status == "ok"
    assert result.pages_attempted == 2
    assert len(calls) == 2
    assert [call.params["offset"] for call in calls] == ["0", "1"]
    assert "pagination_cap_reached" in result.warnings
    assert len({listing.item_id for listing in result.listings}) == len(result.listings)


def test_config_rejects_unbounded_settings_and_retries_remain_zero():
    with pytest.raises(ValueError):
        EbayBrowseConfig(page_size=MAX_PAGE_SIZE + 1)
    assert MAX_RETRIES == 0


def test_live_transport_builds_browse_get_without_exposing_token():
    seen: dict[str, Any] = {}

    class _Resp:
        status = 200

        def read(self):
            return b'{"itemSummaries":[]}'

        def getcode(self):
            return 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def opener(request, timeout):
        seen["url"] = request.full_url
        seen["headers"] = {k.lower(): v for k, v in request.header_items()}
        seen["timeout"] = timeout
        seen["method"] = request.get_method()
        return _Resp()

    transport = LiveEbayBrowseTransport(
        credential_ref="credential-ebay-browse",
        token_resolver=lambda ref: f"token-for-{ref}",
        opener=opener,
    )
    payload = transport(
        EbayBrowseRequest(
            "/buy/browse/v1/item_summary/search",
            "EBAY_GB",
            "espresso",
            {"q": "espresso", "limit": "1", "offset": "0"},
        ),
        timeout_s=5.0,
    )
    assert payload == {"itemSummaries": []}
    assert seen["method"] == "GET"
    assert "buy/browse/v1/item_summary/search" in seen["url"]
    assert seen["headers"]["authorization"] == "Bearer token-for-credential-ebay-browse"
    assert seen["headers"]["x-ebay-c-marketplace-id"] == "EBAY_GB"
    assert "token-for-credential-ebay-browse" not in str(payload)


def test_live_transport_maps_http_errors():
    import urllib.error

    def make_opener(code):
        def opener(request, timeout):  # noqa: ARG001
            raise urllib.error.HTTPError(
                url="https://api.ebay.com/x",
                code=code,
                msg="no",
                hdrs=None,
                fp=io.BytesIO(b""),
            )

        return opener

    for code, exc_type in ((401, PermissionError), (403, PermissionError), (429, EbayBrowseRateLimitError), (500, RuntimeError)):
        transport = LiveEbayBrowseTransport(
            credential_ref="credential-ebay-browse",
            token_resolver=lambda ref: "tok",
            opener=make_opener(code),
        )
        with pytest.raises(exc_type):
            transport(
                EbayBrowseRequest("/buy/browse/v1/item_summary/search", "EBAY_US", "q", {"q": "q", "limit": "1", "offset": "0"}),
                timeout_s=1.0,
            )


def test_source_confidence_is_not_fabricated_and_observed_at_is_preserved():
    transport = FixtureEbayBrowseTransport(response(item()))
    result = EbayBrowseAdapter(config(), transport=transport).search_brief(
        {"candidate_id": "espresso-1", "query": "espresso"}
    )
    assert result.evidence[0].source_confidence == 0.0
    assert result.listings[0].observed_at == "fixture_deterministic"
    assert result.evidence[0].observed_at == "fixture_deterministic"
