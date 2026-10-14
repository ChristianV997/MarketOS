"""Offline contracts for Mercado Libre listing observations, never sales velocity."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from backend.adapters import mercadolibre_trends as adapter
from backend.adapters.research.market_sources import MercadoLibreResearchAdapter
from backend.adapters.research.trend_source_v1 import AdapterFetchError
from evaluation.commerce.marketplace_trends import build_report, evidence_field_status


OBSERVED = "2026-10-01T12:00:00+00:00"
CANARY = "sk_live_SYNTHETIC_CANARY_ONLY"


def listing(**changes):
    return {
        "id": "MLM123456",
        "site_id": "MLM",
        "title": "Synthetic adjustable desk light",
        "price": 0,
        "currency_id": "MXN",
        "available_quantity": 1,
        "sold_quantity": 320,
        "permalink": "https://articulo.mercadolibre.com.mx/MLM-123456",
        "category_id": "MLM1000",
        "shipping": {"free_shipping": False},
        **changes,
    }


class Response:
    def __init__(self, rows=None, *, status=200, body=None, chunk_size=17):
        self.status_code = status
        self.body = body if body is not None else json.dumps({"results": rows or []}).encode()
        self.chunk_size = chunk_size
        self.closed = False
        self.chunks_read = 0

    def iter_content(self, chunk_size):
        for offset in range(0, len(self.body), self.chunk_size):
            self.chunks_read += 1
            yield self.body[offset:offset + self.chunk_size]

    def close(self):
        self.closed = True


class Transport:
    """Fixture transport; never connects to a socket."""

    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []

    def get(self, url, *, params, timeout):
        self.calls.append((url, params, timeout))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def fetch(*responses, **options):
    return adapter.fetch(
        transport=Transport(*responses), sites=["MLM"], queries=["desk light"],
        observed_at=OBSERVED, **options,
    )


@pytest.mark.parametrize("price", [None, 0, "0.00", "25.75"])
def test_price_currency_and_non_velocity_contract(price):
    record = adapter._item_to_signal(listing(price=price), "MLM", query="desk light", observed_at=OBSERVED)
    assert record["price"] == (None if price is None else float(price))
    assert record["currency"] == "MXN"
    assert record["price_status"] == ("unavailable" if price is None else "fixture")
    assert record["sold_quantity"] == 320
    assert record["available_quantity"] == 1
    assert record["quantity_precision"] == "provider_reference"
    assert record["score"] is None and record["velocity"] is None
    assert record["confidence"] is None
    assert record["listing_id"] == "MLM123456"
    assert record["candidate_id"] is None
    assert record["evidence_mode"] == "fixture"
    assert record["supplier_proof"] is False
    assert record["observed_at"] == OBSERVED
    assert record["permalink"] == listing()["permalink"]


def test_absent_fields_never_get_site_currency_time_or_quantity_defaults():
    record = adapter._item_to_signal({"id": "MLM123456", "title": "Synthetic"}, "MLM")
    for key in ("price", "currency", "observed_at", "available_quantity", "sold_quantity", "shipping_claim", "language", "region"):
        assert record[key] is None
    assert record["source_ref"] == "https://api.mercadolibre.com/items/MLM123456"
    assert "currency_unavailable" in record["warnings"]
    assert "observation_time_unavailable" in record["warnings"]


def test_missing_price_key_and_listing_dates_do_not_invent_observation():
    raw = listing(date_created=OBSERVED, last_updated=OBSERVED)
    raw.pop("price")
    record = adapter._item_to_signal(raw, "MLM")
    assert record["price"] is None and record["observed_at"] is None


@pytest.mark.parametrize("price", [True, -1, "NaN", "Infinity", "oops", {}, 1e309])
def test_malformed_price_is_rejected_without_echo(price):
    with pytest.raises(ValueError) as exc:
        adapter._item_to_signal(listing(price=price), "MLM")
    assert str(price) not in str(exc.value) or str(exc.value) == "invalid_price"


@pytest.mark.parametrize("changes", [
    {"id": None}, {"id": "MLA123456"}, {"site_id": "MLA"},
    {"title": ""}, {"title": CANARY}, {"title": "<script>unsafe</script>"},
    {"currency_id": "mxn"}, {"available_quantity": -1}, {"sold_quantity": True},
    {"shipping": {"free_shipping": "false"}},
    {"permalink": "https://example.test/private"},
    {"permalink": "https://articulo.mercadolibre.com.mx/a?access_token=" + CANARY},
    {"seller": {"access_token": CANARY}},
])
def test_unsafe_or_mismatched_listing_fails_closed(changes):
    with pytest.raises(ValueError) as exc:
        adapter._item_to_signal(listing(**changes), "MLM")
    assert CANARY not in str(exc.value)


@pytest.mark.parametrize("site,query", [("../MLM", "desk"), ("BAD", "desk"), ("mlm", "desk"), ("MLM", ""), ("MLM", "a\x00b"), ("MLM", "a\nb"), ("MLM", "x" * 121), ("MLM", CANARY)])
def test_invalid_request_never_reaches_transport(site, query):
    transport = Transport(Response([listing()]))
    with pytest.raises(ValueError):
        adapter.fetch(transport=transport, sites=[site], queries=[query])
    assert transport.calls == []


@pytest.mark.parametrize("options", [{"max_pages": 0}, {"max_pages": 4}, {"max_pages": True}, {"timeout_seconds": 0}, {"timeout_seconds": float("nan")}, {"evidence_mode": "live_readonly"}, {"observed_at": "2026-10-01"}])
def test_invalid_bounds_and_evidence_labels_fail_before_transport(options):
    transport = Transport(Response([listing()]))
    with pytest.raises(ValueError):
        adapter.fetch(transport=transport, sites=["MLM"], queries=["desk"], **options)
    assert transport.calls == []


def test_default_call_is_observably_blocked_without_requests(monkeypatch):
    request = Mock(side_effect=AssertionError("network forbidden"))
    monkeypatch.setattr("requests.get", request)
    monkeypatch.setenv("MERCADOLIBRE_LIVE", "true")
    with pytest.raises(AdapterFetchError, match="mercadolibre_live_access_blocked"):
        adapter.fetch()
    request.assert_not_called()


def test_request_bounds_response_closure_and_deterministic_replay():
    response = Response([listing()])
    transport = Transport(response)
    first = adapter.fetch(transport=transport, sites=["MLM"], queries=["desk"], observed_at=OBSERVED)
    assert response.closed
    assert transport.calls == [("https://api.mercadolibre.com/sites/MLM/search", {"q": "desk", "limit": 20, "offset": 0}, 8.0)]
    second = adapter.fetch(transport=Transport(Response([listing()])), sites=["MLM"], queries=["desk"], observed_at=OBSERVED)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_pages_are_bounded_without_merging_variant_identities():
    first = listing(variation_id=11)
    second = listing(variation_id=12, price=25)
    rows = fetch(Response([first] * 20), Response([second]), max_pages=2)
    assert len(rows) == 2
    assert {row["variation_id"] for row in rows} == {11, 12}
    assert len({row["source_ref"] for row in rows}) == 2


def test_duplicate_source_observations_collapse_and_conflicts_quarantine_in_every_order():
    for rows in ([listing(), listing()], [listing(), listing(price=10)], [listing(price=10), listing()]):
        if rows[0] == rows[1]:
            assert len(fetch(Response(rows))) == 1
        else:
            with pytest.raises(AdapterFetchError, match="conflicting_listing_observations"):
                fetch(Response(rows))


@pytest.mark.parametrize("status,code", [(401, "auth_required"), (403, "access_denied"), (429, "rate_limited"), (500, "upstream_unavailable")])
def test_http_errors_are_closed_and_non_reflective(status, code, caplog):
    response = Response(status=status, body=CANARY.encode())
    with pytest.raises(AdapterFetchError, match=code) as exc:
        fetch(response)
    assert response.closed
    assert CANARY not in str(exc.value) + caplog.text
    assert response.chunks_read == 0


@pytest.mark.parametrize("body", [b'{"results":null}', b'{"results":{}}', b'[]', b'{"results":[],"results":[]}', b'{"results":[NaN]}', b'\xff', b'{'])
def test_malformed_response_fails_closed_and_closes(body):
    response = Response(body=body)
    with pytest.raises(AdapterFetchError):
        fetch(response)
    assert response.closed


def test_actual_stream_read_is_capped_and_closed():
    response = Response(body=b" " * (adapter.MAX_RESPONSE_BYTES + 100), chunk_size=4096)
    with pytest.raises(AdapterFetchError, match="response_size_exceeded"):
        fetch(response)
    assert response.closed
    assert response.chunks_read <= adapter.MAX_RESPONSE_BYTES // 4096 + 1


def test_response_result_count_is_not_silently_truncated():
    with pytest.raises(AdapterFetchError, match="result_bounds_exceeded"):
        fetch(Response([listing()] * 21))


def test_partial_failure_and_rejected_rows_stay_visible(caplog):
    transport = Transport(TimeoutError(CANARY), Response([listing(), listing(id="bad")]))
    rows = adapter.fetch(transport=transport, sites=["MLM"], queries=["first", "second"], observed_at=OBSERVED)
    assert len(rows) == 1
    assert rows[0]["status"] == "partial"
    assert "source_timeout" in rows[0]["warnings"]
    assert "listing_rejected" in rows[0]["warnings"]
    assert CANARY not in caplog.text + json.dumps(rows)


def test_no_cache_cross_call_site_or_mutation_leakage():
    transport = Transport(Response([listing()]), Response([listing(price=9)]), Response([]))
    options = {"transport": transport, "sites": ["MLM"], "queries": ["desk"]}
    first = adapter.fetch(**options)
    first[0]["price"] = 999
    assert adapter.fetch(**options)[0]["price"] == 9
    assert adapter.fetch(**options) == []
    assert len(transport.calls) == 3


def test_canonical_marketplace_projection_requires_explicit_candidate_binding():
    for value in (None, "", "../candidate"):
        with pytest.raises(ValueError):
            adapter.to_marketplace_evidence(listing(), "MLM", candidate_id=value)
    evidence = adapter.to_marketplace_evidence(listing(), "MLM", candidate_id="desk-light", query="desk", observed_at=OBSERVED, evidence_mode="manual_import")
    assert evidence.candidate_id == "desk-light"
    assert evidence.currency == "MXN" and evidence.price == 0.0
    assert evidence.evidence_mode == "manual_import"
    assert evidence.source_confidence == 0.0
    assert evidence.field_provenance["source_confidence"] == "unavailable"
    assert evidence.search_growth_signal is None and evidence.sold_count_text == "320"
    report = build_report([evidence]).to_dict()
    assert report["candidates"][0]["candidate_id"] == "desk-light"
    assert report["candidates"][0]["evidence"][0]["price"] == 0.0
    assert "supplier_proof_not_observed" in report["candidates"][0]["score"]["reasons"]


def test_canonical_projection_preserves_missing_currency_price_and_time():
    evidence = adapter.to_marketplace_evidence({"id": "MLM123456", "title": "Synthetic"}, "MLM", candidate_id="desk-light")
    assert evidence.price is None and evidence.currency == "" and evidence.observed_at == ""
    assert evidence.field_provenance["price"] == "unavailable"
    assert evidence.field_provenance["observed_at"] == "unavailable"


def test_research_wrapper_rejects_unverified_velocity_even_if_caller_supplies_one():
    for raw in (listing(), {"product": "Synthetic", "velocity": 0.9}, {"product": "Synthetic"}):
        with pytest.raises(AdapterFetchError, match="listing_evidence_is_not_sales_velocity"):
            MercadoLibreResearchAdapter().to_canonical(raw, fetched_at=datetime(2026, 1, 1, tzinfo=timezone.utc))


def test_signal_engine_reports_blocked_source_without_fabricated_data():
    from core.signals import SignalEngine

    engine = SignalEngine()
    adapter.register(engine)
    assert all(row["source"] == "mock" for row in engine.get(force_refresh=True))
    assert engine.cache_stats()["source_failures"]["mercadolibre"] == 1


def test_signal_engine_preserves_other_sources_and_records_mercadolibre_failure():
    from core.signals import SignalEngine

    engine = SignalEngine()
    engine.register_source("fixture-other", lambda: [{"product": "Synthetic", "source": "fixture-other"}])
    adapter.register(engine)
    assert engine.get(force_refresh=True) == [{"product": "Synthetic", "source": "fixture-other"}]
    assert engine.cache_stats()["source_failures"]["mercadolibre"] == 1


def test_research_unavailable_is_not_retried_or_persisted():
    from backend.jobs.research_trend_v1 import _fetch_records

    source = MercadoLibreResearchAdapter()
    source.fetcher = Mock(wraps=adapter.fetch)
    metrics = Mock()
    with pytest.raises(AdapterFetchError, match="mercadolibre_live_access_blocked"):
        _fetch_records(source, metrics=metrics)
    source.fetcher.assert_called_once_with()
    metrics.record_retry.assert_not_called()


def test_transport_exception_cannot_reflect_provider_error_subclass(caplog):
    with pytest.raises(AdapterFetchError) as exc:
        fetch(adapter.MercadoLibreEvidenceError(CANARY))
    assert CANARY not in str(exc.value) + caplog.text


def test_request_sequences_are_bounded_before_iteration():
    def unexpected_iterator():
        raise AssertionError("must not consume arbitrary iterator")
        yield "MLM"

    transport = Transport()
    with pytest.raises(ValueError):
        adapter.fetch(transport=transport, sites=unexpected_iterator(), queries=["desk"])
    assert transport.calls == []


@pytest.mark.parametrize("options", [
    {"sites": ["MLM", "MLA", "MLB", "MLC"], "queries": ["desk"]},
    {"sites": ["MLM"], "queries": list("abcdefg")},
    {"sites": ["MLM", "MLA", "MLB"], "queries": ["a", "b", "c"], "max_pages": 3},
])
def test_total_request_budget_is_validated_before_transport(options):
    transport = Transport()
    with pytest.raises(ValueError):
        adapter.fetch(transport=transport, **options)
    assert transport.calls == []


def test_exact_byte_boundary_and_output_cap(monkeypatch):
    content = b'{"results":[]}'
    response = Response(body=content + b" " * (adapter.MAX_RESPONSE_BYTES - len(content)), chunk_size=4096)
    assert fetch(response) == [] and response.closed
    monkeypatch.setattr(adapter, "MAX_OUTPUT_BYTES", 10)
    with pytest.raises(AdapterFetchError, match="output_size_exceeded"):
        fetch(Response([listing()]))


def test_interrupted_read_closes_response_and_is_not_hidden():
    class Interrupted(Response):
        def iter_content(self, chunk_size):
            yield b'{"results":'
            raise KeyboardInterrupt

    response = Interrupted()
    with pytest.raises(KeyboardInterrupt):
        fetch(response)
    assert response.closed


def test_fetched_manual_listing_reaches_existing_report_without_reclassification():
    record = fetch(Response([listing(price=None)]), evidence_mode="manual_import")[0]
    evidence = adapter.to_marketplace_evidence(record, "MLM", candidate_id="desk-light")
    report = build_report([evidence], evidence_mode="manual_import").to_dict()
    actual = report["candidates"][0]["evidence"][0]
    assert actual["candidate_id"] == "desk-light"
    assert actual["price"] is None and actual["currency"] == "MXN"
    assert actual["evidence_mode"] == "manual_import"
    assert actual["observed_at"] == OBSERVED
    assert actual["source_url"] == record["source_ref"]


def test_candidate_binding_cannot_export_secret_shaped_id():
    with pytest.raises(ValueError):
        adapter.to_marketplace_evidence(listing(), "MLM", candidate_id=CANARY)


@pytest.mark.parametrize("price", ["1e-400", "100000000000000.01", "10.00000000000000001"])
def test_lossy_price_conversion_cannot_erase_zero_distinction_or_conflicts(price):
    with pytest.raises(ValueError, match="invalid_price"):
        adapter._item_to_signal(listing(price=price), "MLM")


@pytest.mark.parametrize("mode", ["fixture", "manual_import"])
def test_canonical_field_names_keep_their_evidence_class(mode):
    evidence = adapter.to_marketplace_evidence(listing(), "MLM", candidate_id="desk-light", evidence_mode=mode)
    for field in ("sold_count_text", "availability", "shipping_signal", "source_url", "query", "category_id"):
        expected = "unavailable" if field == "query" else mode
        assert evidence_field_status(evidence, field) == expected


def test_batch_projection_closes_shared_report_order_dependent_dedup_seam():
    original = fetch(Response([listing(price=10)]))[0]
    conflicting = fetch(Response([listing(price=20)]))[0]
    bindings = {original["source_ref"]: "desk-light"}
    for records in ([original, conflicting], [conflicting, original]):
        with pytest.raises(ValueError, match="conflicting_listing_observations"):
            adapter.project_marketplace_evidence(records, candidate_bindings=bindings)
    first = adapter.project_marketplace_evidence([original, original], candidate_bindings=bindings)
    assert len(first) == 1
    assert build_report(first).to_dict() == build_report(adapter.project_marketplace_evidence([original], candidate_bindings=bindings)).to_dict()


def test_batch_projection_rejects_raw_alias_keys():
    rows = [listing(price=value, source_ref=f"alias-{value}") for value in (10, 20)]
    with pytest.raises(ValueError):
        adapter.project_marketplace_evidence(rows, candidate_bindings={"alias-10": "desk", "alias-20": "desk"})


@pytest.mark.parametrize("field,changed", [("title", "Different synthetic listing"), ("permalink", "https://mercadolibre.com.mx/different")])
def test_batch_projection_detects_conflicts_before_discarding_listing_fields(field, changed):
    original = fetch(Response([listing()]))[0]
    conflicting = fetch(Response([listing(**{field: changed})]))[0]
    for rows in ([original, conflicting], [conflicting, original]):
        with pytest.raises(ValueError, match="conflicting_listing_observations"):
            adapter.project_marketplace_evidence(rows, candidate_bindings={original["source_ref"]: "desk"})


def test_signed_zero_duplicate_projection_is_byte_deterministic():
    rows = [fetch(Response([listing(price=value)]))[0] for value in ("-0", "0")]
    bindings = {rows[0]["source_ref"]: "desk"}
    forward = build_report(adapter.project_marketplace_evidence(rows, candidate_bindings=bindings)).to_dict()
    reverse = build_report(adapter.project_marketplace_evidence(list(reversed(rows)), candidate_bindings=bindings)).to_dict()
    assert json.dumps(forward, sort_keys=True) == json.dumps(reverse, sort_keys=True)


def test_identical_listing_across_queries_uses_deterministic_query():
    rows = [adapter.fetch(transport=Transport(Response([listing()])), sites=["MLM"], queries=[query], observed_at=OBSERVED)[0] for query in ("z desk", "a desk")]
    bindings = {rows[0]["source_ref"]: "desk"}
    forward = adapter.project_marketplace_evidence(rows, candidate_bindings=bindings)
    reverse = adapter.project_marketplace_evidence(list(reversed(rows)), candidate_bindings=bindings)
    assert forward == reverse and len(forward) == 1 and forward[0].query == "a desk"


@pytest.mark.parametrize("updates,options", [
    ({"source_ref": "https://api.mercadolibre.com/items/MLM999"}, {}),
    ({"site_id": "MLA"}, {}), ({"evidence_mode": None}, {}),
    ({}, {"evidence_mode": "manual_import"}),
    ({}, {"observed_at": "2026-10-02T12:00:00+00:00"}),
])
def test_fetched_observation_projection_cannot_rebind_identity_or_evidence(updates, options):
    record = fetch(Response([listing()]))[0]
    record.update(updates)
    with pytest.raises(ValueError):
        adapter.to_marketplace_evidence(record, "MLM", candidate_id="desk-light", **options)


@pytest.mark.parametrize("first,second", [
    ("backend.adapters.mercadolibre_trends", "backend.adapters.research.market_sources"),
    ("backend.adapters.research.market_sources", "backend.adapters.mercadolibre_trends"),
])
def test_cold_import_orders_do_not_create_a_cycle(first, second):
    result = subprocess.run(
        [sys.executable, "-c", f"import importlib; importlib.import_module('{first}'); importlib.import_module('{second}')"],
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert result.returncode == 0
