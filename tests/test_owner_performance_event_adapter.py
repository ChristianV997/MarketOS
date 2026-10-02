"""Owner performance event adapter: events that exist -> report payload, no invented inputs.

Shopify events come from the real producers (``normalize_shopify_export`` +
``shopify_batch_events``). Ledger events are built with the real
``Event.from_workflow_record``; the ledger writers do not record ``currency`` or
``evidence_class`` today, so the tests that include them add those fields
SYNTHETICALLY to prove the gate, and the "as written today" tests prove they are
refused. The final class runs the payload through the real report builder when
it is importable (it lives on PR #368 and is skipped on a base without it).
"""
from __future__ import annotations

import importlib.util
import json
import random
import re
import unicodedata
from decimal import Decimal

import pytest

from backend.commerce.owner_performance_event_adapter import (
    NOT_MAPPED_REASONS,
    OwnerPerformanceEventAdapterError,
    adapt_events_to_performance_report_payload as adapt,
)
from backend.contracts.events import Event
from backend.ecommerce.shopify_readonly.events import shopify_batch_events
from backend.ecommerce.shopify_readonly.importer import build_store_context, normalize_shopify_export

WS = "ws-owner-1"
PERIOD = {"period_start": "2026-03-01", "period_end": "2026-03-31", "currency": "USD"}


def order(order_id: str, **over):
    base = {
        "id": order_id, "name": f"#{order_id}", "created_at": "2026-03-10T12:00:00Z", "currency": "USD",
        "subtotal_price": "40.00", "total_price": "52.40", "total_tax": "2.40", "total_discounts": "0.00",
        "financial_status": "paid", "fulfillment_status": "fulfilled", "line_items": [],
    }
    base.update(over)
    return base


def shopify_events(orders, *, workspace=WS, mode="fixture", source="manual://shopify-export"):
    batch = normalize_shopify_export({"orders": orders}, workspace, mode, None, source)
    return shopify_batch_events(batch, build_store_context(batch))


def ledger_event(name: str, ts: float, workspace=WS, **data):
    record = {"event": name, "ts": ts, "workflow_id": f"ledger-{name}-{ts}", "data": {"workspace_id": workspace, "ts": ts, **data}}
    return Event.from_workflow_record(record)


def run(events, **over):
    return adapt(events, workspace_id=WS, **{**PERIOD, **over})


def amounts(result, metric=None):
    """Exact decimals; the Shopify producer stores floats, so 40.00 arrives as 40.0 (same value)."""
    return [Decimal(line["amount"]) for line in lines_of(result, metric)]


def lines_of(result, metric=None):
    return [line for line in result.payload["lines"] if metric is None or line["metric"] == metric]


MARCH_10 = 1_773_144_000.0  # 2026-03-10T12:00:00Z


# ------------------------------------------------------------ Shopify revenue mapping

def test_shopify_orders_become_revenue_lines_with_class_currency_and_source_refs():
    events = shopify_events([order("1001"), order("1002", subtotal_price="10.50", created_at="2026-03-12T09:30:00-05:00")])
    result = run(events)
    revenue = lines_of(result, "revenue")
    assert [(Decimal(line["amount"]), line["currency"], line["occurred_on"]) for line in revenue] == [(Decimal("40"), "USD", "2026-03-10"), (Decimal("10.5"), "USD", "2026-03-12")]
    assert {line["evidence_class"] for line in revenue} == {"fixture"}
    assert all(line["campaign_id"] is None for line in revenue)
    for line in revenue:
        ref = line["evidence_ref"]
        assert ref["source_type"] == "canonical_event" and ref["origin"] == "backend.ecommerce.shopify_readonly"
        assert ref["document_ref"].startswith("shopify_order:") and len(ref["snapshot_hash"]) == 64
        assert ref["evidence_state"] == "fixture"
        assert "amount_is_subtotal_excluding_tax_and_shipping" in ref["warnings"]
    assert {r["event_id"] for r in result.coverage["source_refs"]} == {line["evidence_ref"]["evidence_id"] for line in revenue}
    assert all(len(r["replay_hash"]) == 64 for r in result.coverage["source_refs"])


def test_revenue_is_subtotal_not_total_price_and_manual_mode_maps_to_manual_class():
    result = run(shopify_events([order("1", subtotal_price="40.00", total_price="999.00")], mode="manual"))
    (line,) = lines_of(result, "revenue")
    assert Decimal(line["amount"]) == Decimal("40"), "tax/shipping-inclusive total_price is never used"
    assert line["evidence_class"] == "manual" and line["evidence_ref"]["evidence_state"] == "unknown"


def test_other_import_modes_are_not_guessed_and_observed_is_never_produced():
    for mode in ("live", "observed", "api", "verified", ""):
        result = run(shopify_events([order("1")], mode=mode))
        assert lines_of(result) == [], mode
        assert result.coverage["excluded"] == {"evidence_class_unrecognized": 1}, mode
    for mode in ("fixture", "manual"):
        assert run(shopify_events([order("1")], mode=mode)).coverage["claims"]["observed_class_produced"] is False


def test_period_date_is_taken_as_written_without_timezone_shifting():
    result = run(shopify_events([order("1", created_at="2026-03-31T23:30:00-05:00")]))
    (line,) = lines_of(result, "revenue")
    assert line["occurred_on"] == "2026-03-31"
    assert "order_created_at=2026-03-31T23:30:00-05:00" in line["evidence_ref"]["warnings"]
    assert "no timezone shifting" in result.coverage["date_policy"]


def test_period_and_currency_are_preserved_and_filtering_is_left_to_the_report():
    result = run(shopify_events([order("1", created_at="2026-02-27T10:00:00Z"), order("2", created_at="2026-04-02T10:00:00Z"), order("3")]))
    assert (result.payload["period_start"], result.payload["period_end"], result.payload["currency"]) == ("2026-03-01", "2026-03-31", "USD")
    assert len(lines_of(result)) == 3 and result.coverage["lines_in_period"] == 1
    assert result.coverage["period_filtering"] == "delegated_to_report"


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"cancelled_at": "2026-03-11T00:00:00Z"}, "order_cancelled"),
        ({"financial_status": "pending"}, "order_not_paid"),
        ({"financial_status": "voided"}, "order_not_paid"),
        ({"financial_status": "authorized"}, "order_not_paid"),
        ({"financial_status": "partially_paid"}, "order_not_paid"),
        ({"financial_status": ""}, "order_not_paid"),
        ({"subtotal_price": None}, "amount_unavailable"),
        ({"subtotal_price": "-5.00"}, "amount_unavailable"),
        ({"currency": None}, "currency_unavailable"),
        ({"currency": "unknown"}, "currency_unavailable"),
        ({"created_at": None}, "order_date_unavailable"),
        ({"created_at": "last tuesday"}, "order_date_unavailable"),
    ],
)
def test_orders_that_cannot_be_proven_are_excluded_with_a_reason_not_zeroed(override, reason):
    result = run(shopify_events([order("1", **override)]))
    assert lines_of(result) == []
    assert result.coverage["excluded"] == {reason: 1}
    assert result.coverage["all_supported_events_used"] is False
    assert "revenue" in result.coverage["metrics_without_lines"]


def test_explicit_zero_subtotal_is_a_real_zero_but_a_missing_subtotal_is_not():
    free = run(shopify_events([order("1", subtotal_price="0.00")]))
    assert amounts(free, "revenue") == [Decimal("0")]
    assert run(shopify_events([order("1", subtotal_price=None)])).payload["lines"] == []


def test_refunded_orders_keep_gross_revenue_but_flag_that_refund_amounts_are_not_in_the_event():
    result = run(shopify_events([order("1", financial_status="partially_refunded"), order("2", financial_status="refunded")]))
    assert len(lines_of(result, "revenue")) == 2 and lines_of(result, "refunds") == []
    assert result.coverage["notes"] == {"revenue_orders_with_unquantified_refunds": 2}
    assert all("order_has_refund_status_refund_amount_not_in_event" in line["evidence_ref"]["warnings"] for line in lines_of(result))
    assert "refunds" in result.coverage["metrics_without_lines"], "refund status is never turned into a refund amount or a zero"


def test_other_currencies_are_excluded_visibly_never_converted_or_merged():
    result = run(shopify_events([order("1"), order("2", currency="EUR", subtotal_price="99.00")]))
    assert [line["currency"] for line in lines_of(result)] == ["USD"]
    assert result.coverage["excluded"] == {"currency_mismatch": 1}


# ------------------------------------------------------------ workspace separation

def test_events_from_other_or_unattributed_workspaces_never_count():
    mine = shopify_events([order("1")])
    theirs = shopify_events([order("9", subtotal_price="500.00")], workspace="ws-someone-else")
    unscoped = [Event(e.event_id + "-u", None, e.aggregate_type, e.aggregate_id, e.event_type, 1, e.occurred_at, source=e.source, payload=e.payload, metadata=e.metadata) for e in shopify_events([order("8", subtotal_price="77.00")], workspace="x") if e.event_type == "shopify_order_observed"]
    result = run([*mine, *theirs, *unscoped])
    assert amounts(result) == [Decimal("40")]
    assert result.coverage["excluded"] == {"other_workspace": 1, "workspace_unattributed": 1}
    assert "ws-someone-else" not in str(result.coverage), "other tenants' ids are counted, never echoed"


def test_ledger_event_with_contradicting_workspace_fields_is_unattributable():
    event = Event("e1", "ws-a", "workflow", "w1", "AdSpendObserved", 1, MARCH_10, source="x", payload={"workspace_id": "ws-b", "amount": 5, "currency": "USD", "evidence_class": "manual"})
    result = adapt([event], workspace_id="ws-a", **PERIOD)
    assert result.payload["lines"] == [] and result.coverage["excluded"] == {"workspace_unattributed": 1}


# ------------------------------------------------------------ idempotency and determinism

def test_replayed_batches_and_duplicate_event_ids_do_not_double_count():
    events = shopify_events([order("1"), order("2", subtotal_price="10.00")])
    once = run(events)
    twice = run([*events, *events])
    assert twice.payload == once.payload and twice.fingerprint != "" and twice.coverage["duplicate_event_ids_ignored"] == len(events)
    assert sum(amounts(twice, "revenue")) == Decimal("50")


def test_reimport_in_a_new_batch_counts_each_order_once_newest_observation_wins():
    first = shopify_events([order("1", subtotal_price="40.00")], source="manual://export-1")
    second = shopify_events([order("1", subtotal_price="45.00"), order("2", subtotal_price="5.00")], source="manual://export-2")
    for event in second:  # make the second import strictly newer
        object.__setattr__(event, "occurred_at", event.occurred_at + 10_000)
    result = run([*first, *second])
    assert sorted(amounts(result, "revenue")) == [Decimal("5"), Decimal("45")]
    assert run([*second, *first]).to_dict() == result.to_dict(), "the newest observation wins whatever order events arrive in"
    assert result.coverage["shopify_orders"] == {"distinct_orders": 2, "older_duplicate_observations_dropped": 1, "conflicting_duplicate_observations": 1}


def test_identical_reimport_is_a_duplicate_not_a_conflict():
    first = shopify_events([order("1")], source="manual://a")
    second = shopify_events([order("1")], source="manual://b")
    for event in second:
        object.__setattr__(event, "occurred_at", event.occurred_at + 10_000)
    result = run([*first, *second])
    assert len(lines_of(result)) == 1
    # Identical content hashes to the same batch id, so the events are the same events: caught by event_id.
    assert result.coverage["duplicate_event_ids_ignored"] == len(first)
    assert result.coverage["shopify_orders"]["conflicting_duplicate_observations"] == 0


def test_a_newer_cancellation_removes_an_order_an_older_import_had_as_paid():
    first = shopify_events([order("1")], source="manual://a")
    second = shopify_events([order("1", cancelled_at="2026-03-20T00:00:00Z")], source="manual://b")
    for event in second:
        object.__setattr__(event, "occurred_at", event.occurred_at + 10_000)
    result = run([*first, *second])
    assert lines_of(result) == [] and result.coverage["excluded"] == {"order_cancelled": 1}


def test_output_is_independent_of_input_order():
    events = [*shopify_events([order(str(i), subtotal_price=f"{i}.00") for i in range(1, 7)]), ledger_event("AdSpendObserved", MARCH_10, amount=12.5, currency="USD", evidence_class="manual")]
    baseline = run(events)
    for seed in range(5):
        shuffled = list(events)
        random.Random(seed).shuffle(shuffled)
        assert run(shuffled).to_dict() == baseline.to_dict()


# ------------------------------------------------------------ ledger events: gated, never guessed

def test_ledger_events_as_written_today_are_refused_not_defaulted():
    events = [
        ledger_event("RefundIssued", MARCH_10, order_id="1", amount=10.0),
        ledger_event("SupplierCostObserved", MARCH_10, order_id="1", product_name="x", amount=12.0),
        ledger_event("AdSpendObserved", MARCH_10, channel="meta", amount=30.0, product_name="x"),
    ]
    result = run(events)
    assert result.payload["lines"] == []
    assert result.coverage["excluded"] == {"currency_not_recorded": 3}
    assert {"refunds", "product_cost", "ad_spend"} <= set(result.coverage["metrics_without_lines"])


def test_ledger_events_with_recorded_currency_and_class_map_to_their_metrics_unchanged():
    events = [
        ledger_event("RefundIssued", MARCH_10, order_id="1", amount=10.0, currency="usd", evidence_class="manual"),
        ledger_event("SupplierCostObserved", MARCH_10 + 1, order_id="1", amount=12.34, currency="USD", evidence_class="fixture"),
        ledger_event("AdSpendObserved", MARCH_10 + 2, channel="meta", amount=30.0, currency="USD", evidence_class="observed"),
    ]
    result = run(events)
    by_metric = {line["metric"]: line for line in result.payload["lines"]}
    assert set(by_metric) == {"refunds", "product_cost", "ad_spend"}
    assert (Decimal(by_metric["product_cost"]["amount"]), by_metric["product_cost"]["evidence_class"]) == (Decimal("12.34"), "fixture")
    assert by_metric["ad_spend"]["evidence_class"] == "observed" and by_metric["ad_spend"]["occurred_on"] == "2026-03-10"
    assert by_metric["refunds"]["currency"] == "USD"
    assert all(line["campaign_id"] is None for line in result.payload["lines"]), "channel is never promoted to a campaign"


def test_ledger_zero_amount_is_not_trusted_because_writers_default_to_zero():
    result = run([ledger_event("AdSpendObserved", MARCH_10, channel="meta", amount=0.0, currency="USD", evidence_class="manual")])
    assert result.payload["lines"] == []
    assert result.coverage["excluded"] == {"zero_amount_not_distinguishable_from_default": 1}


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        ({"amount": 5.0, "currency": "USD"}, "evidence_class_not_recorded"),
        ({"amount": 5.0, "currency": "USD", "evidence_class": "verified"}, "evidence_class_not_recorded"),
        ({"amount": None, "currency": "USD", "evidence_class": "manual"}, "amount_unavailable"),
        ({"amount": "n/a", "currency": "USD", "evidence_class": "manual"}, "amount_unavailable"),
        ({"amount": -3.0, "currency": "USD", "evidence_class": "manual"}, "amount_unavailable"),
        ({"amount": True, "currency": "USD", "evidence_class": "manual"}, "amount_unavailable"),
        ({"amount": 5.0, "currency": "dollars", "evidence_class": "manual"}, "currency_not_recorded"),
    ],
)
def test_ledger_events_missing_or_invalid_inputs_are_excluded_with_a_reason(data, reason):
    result = run([ledger_event("AdSpendObserved", MARCH_10, **data)])
    assert result.payload["lines"] == [] and result.coverage["excluded"] == {reason: 1}


def test_an_observed_claim_is_refused_when_the_event_itself_says_dry_run_or_advisory():
    event = ledger_event("AdSpendObserved", MARCH_10, amount=9.0, currency="USD", evidence_class="observed")
    flagged = Event(event.event_id, event.workspace_id, event.aggregate_type, event.aggregate_id, event.event_type, 1, event.occurred_at, source=event.source, payload=event.payload, metadata={"dry_run": True})
    result = run([flagged])
    assert result.payload["lines"] == [] and result.coverage["excluded"] == {"observed_claim_contradicted_by_metadata": 1}


def test_identical_ledger_records_are_deduplicated_but_distinct_refunds_are_both_kept():
    same = [ledger_event("RefundIssued", MARCH_10, order_id="1", amount=4.0, currency="USD", evidence_class="manual") for _ in range(2)]
    # Different event ids (as the legacy store would mint), identical content.
    same[1] = Event("other-id", same[1].workspace_id, same[1].aggregate_type, same[1].aggregate_id, same[1].event_type, 1, same[1].occurred_at, source=same[1].source, payload=same[1].payload, metadata=same[1].metadata)
    assert len(lines_of(run(same), "refunds")) == 1 and run(same).coverage["ledger_duplicates_ignored"] == 1
    distinct = [ledger_event("RefundIssued", MARCH_10 + i, order_id="1", amount=4.0, currency="USD", evidence_class="manual") for i in range(2)]
    assert len(lines_of(run(distinct), "refunds")) == 2, "two partial refunds of the same amount at different times are real"


# ------------------------------------------------------------ what is never sourced

def test_shipping_and_fees_are_never_sourced_and_missing_metrics_stay_missing():
    result = run(shopify_events([order("1")]))
    assert result.coverage["metrics_never_sourced"] == ["shipping_cost", "fees"]
    assert result.coverage["metrics_with_lines"] == ["revenue"]
    assert set(result.coverage["metrics_without_lines"]) == {"refunds", "product_cost", "shipping_cost", "fees", "ad_spend"}
    assert {line["metric"] for line in result.payload["lines"]} == {"revenue"}, "no zero or placeholder line for any absent metric"


def test_money_related_events_that_are_intentionally_unmapped_are_counted_with_the_reason():
    events = [
        ledger_event("OrderCreated", MARCH_10, order_id="1", revenue=99.0),
        ledger_event("PaymentCaptured", MARCH_10, order_id="1", amount=99.0),
        ledger_event("ChargebackOpened", MARCH_10, order_id="1", amount=99.0),
        ledger_event("AttributionClaimObserved", MARCH_10, order_id="1", channel="meta", claimed_revenue=500.0),
        Event("m1", WS, "runtime", "r", "metrics.ingested", 1, MARCH_10, source="x", payload={"metrics": {"spend": 10, "revenue": 90}}),
    ]
    result = run(events)
    assert result.payload["lines"] == []
    assert result.coverage["unsupported_event_types"] == {"AttributionClaimObserved": 1, "ChargebackOpened": 1, "OrderCreated": 1, "PaymentCaptured": 1, "metrics.ingested": 1}
    assert set(result.coverage["intentionally_not_mapped"]) == set(result.coverage["unsupported_event_types"])
    assert all(reason for reason in NOT_MAPPED_REASONS.values())


def test_no_causal_or_live_claims_and_read_only_flags_are_always_stated():
    coverage = run(shopify_events([order("1")])).coverage
    assert coverage["claims"] == {"campaign_lift": False, "causal_attribution": False, "ads_ran_proven": False, "live_platform_validated": False, "observed_class_produced": False}
    assert coverage["safety"] == {
        "read_only": True, "network_calls": False, "provider_calls": False, "mutated": False,
        "ads_launched": False, "payments_created": False, "publishing": False, "launch_authorized": False,
    }
    assert "campaign" not in {key for line in run(shopify_events([order("1")])).payload["lines"] for key in line if line.get("campaign_id")}


def test_empty_input_yields_an_empty_payload_not_zeros():
    result = run([])
    assert result.payload == {"currency": "USD", "period_start": "2026-03-01", "period_end": "2026-03-31", "lines": []}
    assert result.coverage["lines_emitted"] == 0 and result.coverage["all_supported_events_used"] is True


# ------------------------------------------------------------ input validation

@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"workspace_id": ""}, "invalid_workspace"),
        ({"workspace_id": None}, "invalid_workspace"),
        ({"period_start": "2026-3-1"}, "invalid_period"),
        ({"period_end": 20260331}, "invalid_period"),
        ({"period_start": "2026-04-01", "period_end": "2026-03-01"}, "period_end_before_start"),
        ({"currency": None}, "invalid_currency"),
        ({"currency": "dollars"}, "invalid_currency"),
    ],
)
def test_invalid_scope_arguments_fail_closed(kwargs, code):
    args = {"workspace_id": WS, **PERIOD, **kwargs}
    with pytest.raises(OwnerPerformanceEventAdapterError) as exc:
        adapt([], **args)
    assert exc.value.code == code


def test_non_event_inputs_and_oversized_input_fail_closed():
    for bad in ("not events", b"x", [{"event_type": "shopify_order_observed"}], [object()]):
        with pytest.raises(OwnerPerformanceEventAdapterError) as exc:
            adapt(bad, workspace_id=WS, **PERIOD)
        assert exc.value.code in {"events_must_be_sequence", "invalid_event"}
    with pytest.raises(OwnerPerformanceEventAdapterError) as exc:
        adapt([None] * 50_001, workspace_id=WS, **PERIOD)
    assert exc.value.code == "too_many_events"


def test_the_adapter_does_not_mutate_its_input_events():
    events = shopify_events([order("1")])
    before = [event.canonical_json() for event in events]
    run(events)
    assert [event.canonical_json() for event in events] == before


# ------------------------------------------------------------ privacy-safe references, hostile events, amount hygiene

def shopify_event(**over):
    (event,) = [e for e in shopify_events([order("1")]) if e.event_type == "shopify_order_observed"]
    fields = {name: getattr(event, name) for name in ("event_id", "workspace_id", "aggregate_type", "aggregate_id", "event_type", "schema_version", "occurred_at", "source", "payload", "metadata")}
    return Event(**{**fields, **over})


def _fields(event):
    return {name: getattr(event, name) for name in ("workspace_id", "aggregate_type", "aggregate_id", "event_type", "schema_version", "occurred_at", "source", "payload", "metadata")}


def no_control_chars(value) -> bool:
    """Walks the strings themselves: json.dumps would escape a control character and hide it."""
    if isinstance(value, str):
        return not any(unicodedata.category(char) == "Cc" for char in value)
    if isinstance(value, dict):
        return all(no_control_chars(key) and no_control_chars(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return all(no_control_chars(item) for item in value)
    return True


@pytest.mark.parametrize(
    "source",
    ["/home/user/secret/export.csv?token=abc", "https://user:pw@shop.example/export?key=1", "manual://a/b", "manual://x?y=1", "C:\\exports\\orders.csv", "manual://" + "a" * 80],
)
def test_source_paths_urls_and_credentials_are_withheld_not_echoed(source):
    event = shopify_event(metadata={**shopify_event().metadata, "source": source})
    result = run([event])
    (line,) = lines_of(result, "revenue")
    ref = line["evidence_ref"]
    assert ref["source_url"] == "" and "source_reference_withheld" in ref["warnings"]
    for leaked in ("secret", "token", "pw", "shop.example", "exports", "key=1"):
        assert leaked not in json.dumps(result.to_dict()), leaked


def test_a_plain_scheme_label_source_is_kept_for_provenance():
    result = run(shopify_events([order("1")], source="manual://shopify-export-1"))
    (line,) = lines_of(result, "revenue")
    assert line["evidence_ref"]["source_url"] == "manual://shopify-export-1"
    assert "source_reference_withheld" not in line["evidence_ref"]["warnings"]


def test_customer_and_order_text_never_reaches_the_payload_or_coverage():
    result = run(shopify_events([order("1", customer={"id": "c-1", "email": "buyer@example.test"}, email="buyer@example.test", note="call 555-0100")]))
    blob = json.dumps(result.to_dict())
    for private in ("buyer@example.test", "555-0100", "customer_ref", "order_name", "#1"):
        assert private not in blob, private


@pytest.mark.parametrize("field", ["event_id", "aggregate_id", "source", "aggregate_type"])
def test_a_control_character_in_a_reference_field_is_sanitised_not_passed_to_the_report(field):
    event = shopify_event(**{field: shopify_event().__dict__[field] + "\x07bad"})
    result = run([event])
    assert len(lines_of(result, "revenue")) == 1, "one malformed reference never drops or poisons the line"
    assert no_control_chars(result.to_dict())
    ref = lines_of(result)[0]["evidence_ref"]
    assert re.fullmatch(r"[A-Za-z0-9._:@=+-]{1,128}|ref:[0-9a-f]{16}", ref["evidence_id"])


def test_a_control_character_in_the_metadata_source_is_withheld():
    event = shopify_event(metadata={**shopify_event().metadata, "source": "manual://x\nsecond"})
    ref = lines_of(run([event]))[0]["evidence_ref"]
    assert ref["source_url"] == "" and no_control_chars(ref)


def test_an_unrepresentable_event_time_does_not_crash_the_adapter():
    result = run([shopify_event(occurred_at=1e20)])
    (line,) = lines_of(result, "revenue")
    assert line["evidence_ref"]["captured_at"] == "" and "event_time_unavailable" in line["evidence_ref"]["warnings"]
    ledger = ledger_event("AdSpendObserved", 1e20, amount=5.0, currency="USD", evidence_class="manual")
    assert run([ledger]).coverage["excluded"] == {"event_date_unavailable": 1}


def test_event_id_is_the_identity_a_repeat_with_different_content_is_counted_and_resolves_deterministically():
    first = shopify_event()
    changed = shopify_event(payload={**first.payload, "subtotal_price": 999.0})
    same_time_a, same_time_b = run([first, changed]), run([changed, first])
    assert same_time_a.to_dict() == same_time_b.to_dict(), "identical id and time, different content: order of arrival never decides"
    assert same_time_a.coverage["event_id_content_conflicts"] == 1 and same_time_a.coverage["duplicate_event_ids_ignored"] == 1
    later = shopify_event(payload={**first.payload, "subtotal_price": 999.0}, occurred_at=first.occurred_at + 5)
    result = run([later, first])
    assert amounts(result, "revenue") == [Decimal("40")], "the earliest observation of an id wins, as in the event repository"
    assert result.coverage["event_id_content_conflicts"] == 1
    assert run([first, first]).coverage["event_id_content_conflicts"] == 0, "an exact replay is a duplicate, not a conflict"


def test_equal_timestamps_are_ordered_by_event_id_then_content_independent_of_input_order():
    events = [
        Event(f"e-{n}", None, "workflow", f"w{n}", "AdSpendObserved", 1, MARCH_10, source="legacy.workflow_event_store",
              payload={"workspace_id": WS, "amount": float(n), "currency": "USD", "evidence_class": "manual", "channel": f"c{n}"})
        for n in (3, 1, 2)
    ]
    base = run(events)
    assert [line["evidence_ref"]["evidence_id"] for line in lines_of(base)] == ["e-1", "e-2", "e-3"], "ties resolve by event id"
    for seed in range(4):
        shuffled = list(events)
        random.Random(seed).shuffle(shuffled)
        assert run(shuffled).to_dict() == base.to_dict()


@pytest.mark.parametrize(
    ("amount", "plain"),
    [("1E+3", "1000"), (1e-07, "0.0000001"), ("12.50", "12.50"), (Decimal("2E+2"), "200"), (123456.789, "123456.789")],
)
def test_amounts_are_emitted_as_fixed_point_never_scientific_notation(amount, plain):
    (line,) = lines_of(run([ledger_event("AdSpendObserved", MARCH_10, amount=amount, currency="USD", evidence_class="manual")]))
    assert line["amount"] == plain and "E" not in line["amount"].upper()
    (shop,) = lines_of(run(shopify_events([order("1", subtotal_price=str(amount))])))
    assert Decimal(shop["amount"]) == Decimal(str(amount)) and "E" not in shop["amount"].upper()


@pytest.mark.parametrize("amount", ["1E+999999", "1e15", "1000000000000000", "0.123456789", "9" * 40])
def test_implausible_amounts_are_excluded_with_a_reason_not_passed_to_the_report(amount):
    result = run([ledger_event("AdSpendObserved", MARCH_10, amount=amount, currency="USD", evidence_class="manual")])
    assert result.payload["lines"] == [] and result.coverage["excluded"] == {"amount_out_of_range": 1}
    shop = run(shopify_events([order("1", subtotal_price=amount)]))
    assert shop.payload["lines"] == [] and set(shop.coverage["excluded"]) <= {"amount_out_of_range", "amount_unavailable"}


def test_nothing_in_the_output_implies_launched_ads_payments_publishing_or_live_data():
    result = run([*shopify_events([order("1")], mode="manual"), ledger_event("AdSpendObserved", MARCH_10, channel="meta", amount=15.0, currency="USD", evidence_class="manual"), ledger_event("PaymentCaptured", MARCH_10, order_id="1", amount=99.0)])
    allowed = {"revenue", "refunds", "product_cost", "shipping_cost", "fees", "ad_spend"}
    assert {line["metric"] for line in lines_of(result)} <= allowed, "no payment, payout, campaign or launch metric exists"
    assert result.coverage["unsupported_event_types"]["PaymentCaptured"] == 1 and "PaymentCaptured" in result.coverage["intentionally_not_mapped"]
    assert all(line["campaign_id"] is None for line in lines_of(result))
    safety, claims = result.coverage["safety"], result.coverage["claims"]
    assert not any(safety[key] for key in ("ads_launched", "payments_created", "publishing", "launch_authorized", "network_calls", "provider_calls", "mutated"))
    assert not any(claims.values())
    text = json.dumps(result.payload).lower()
    for word in ("launched", "published", "payout", "payment_captured", "paymentcaptured", "live_readonly", "verified"):
        assert word not in text, word


# ------------------------------------------------------------ with the real report builder (PR #368)

REPORT_PRESENT = importlib.util.find_spec("backend.commerce.owner_performance_report") is not None


@pytest.mark.skipif(not REPORT_PRESENT, reason="backend.commerce.owner_performance_report is on PR #368, not on this base")
class TestThroughTheOwnerPerformanceReport:
    def build(self, payload):
        from backend.commerce.owner_performance_report import build_owner_performance_report

        return build_owner_performance_report(payload).to_dict()

    def test_revenue_only_events_leave_everything_else_unavailable_and_make_no_profit_claim(self):
        report = self.build(run(shopify_events([order("1"), order("2", subtotal_price="10.00")], mode="manual")).payload)
        assert (Decimal(report["revenue"]["amount"]), report["revenue"]["currency"], report["revenue"]["status"]) == (Decimal("50"), "USD", "manual")
        for name in ("refunds", "product_cost", "shipping_cost", "fees", "ad_spend", "contribution", "realized_profit"):
            assert report[name]["amount"] is None and report[name]["status"] == "unavailable", name
        assert report["explicit_zeros"] == []
        assert report["campaigns"] == []
        assert report["evidence_quality"]["claims"] == {"campaign_lift": False, "realized_profit": False, "causal_attribution": False}
        assert report["period_start"] == "2026-03-01" and report["period_end"] == "2026-03-31"

    def test_fixture_class_and_out_of_period_lines_flow_through_unchanged(self):
        report = self.build(run(shopify_events([order("1"), order("2", created_at="2026-05-01T00:00:00Z")])).payload)
        assert Decimal(report["revenue"]["amount"]) == Decimal("40") and report["revenue"]["status"] == "fixture"
        assert report["evidence_quality"]["excluded_after_period"] == 1
        assert report["evidence_quality"]["evidence_classes"] == ["fixture"]

    def test_ledger_costs_with_recorded_currency_complete_ad_spend_but_never_fabricate_the_rest(self):
        events = [
            *shopify_events([order("1")], mode="manual"),
            ledger_event("AdSpendObserved", MARCH_10, channel="meta", amount=15.0, currency="USD", evidence_class="manual"),
        ]
        report = self.build(run(events).payload)
        assert Decimal(report["ad_spend"]["amount"]) == Decimal("15") and report["ad_spend"]["status"] == "manual"
        assert report["contribution"]["amount"] is None and report["realized_profit"]["amount"] is None
        assert report["campaigns"] == [], "channel spend is not campaign attribution"
        assert "ad_spend_required_for_realized_profit" not in report["missing_inputs"]
        assert "refunds_required_for_contribution" in report["missing_inputs"]
        assert report["evidence_quality"]["claims"]["campaign_lift"] is False

    # -- the seam as the owner dashboard (PR #376) reads it: amounts as text, explicit_zeros, evidence classes, safety flags

    def test_mixed_manual_and_fixture_revenue_is_reported_mixed_with_both_classes_and_no_single_source_ref(self):
        events = [*shopify_events([order("1")], mode="fixture", source="manual://fixture-export"), *shopify_events([order("2", subtotal_price="10.00")], mode="manual", source="manual://real-export")]
        report = self.build(run(events).payload)
        assert report["revenue"]["status"] == "mixed" and Decimal(report["revenue"]["amount"]) == Decimal("50")
        assert report["evidence_quality"]["evidence_classes"] == ["fixture", "manual"], "the dashboard's fixture banner keys off this list"
        assert report["revenue"]["evidence_state"] == "unknown" and report["revenue"]["evidence_ref"] is None

    def test_explicit_zero_revenue_is_listed_as_an_explicit_zero_and_a_missing_one_is_not(self):
        zero = self.build(run(shopify_events([order("1", subtotal_price="0.00")])).payload)
        assert zero["explicit_zeros"] == ["revenue"] and re.fullmatch(r"-?(?:0+|0+\.0+)", zero["revenue"]["amount"]), "the dashboard's zero test must match"
        absent = self.build(run(shopify_events([order("1", subtotal_price=None)])).payload)
        assert absent["explicit_zeros"] == [] and absent["revenue"]["amount"] is None and absent["revenue"]["missing_reason"] == "revenue_absent"

    def test_period_bounds_are_inclusive_and_exclusions_are_counted_by_the_report(self):
        orders = [order("a", created_at="2026-02-28T23:59:59Z"), order("b", created_at="2026-03-01T00:00:00Z"), order("c", created_at="2026-03-31T23:59:59Z"), order("d", created_at="2026-04-01T00:00:00Z")]
        report = self.build(run(shopify_events(orders)).payload)
        assert Decimal(report["revenue"]["amount"]) == Decimal("80")
        assert (report["evidence_quality"]["excluded_before_period"], report["evidence_quality"]["excluded_after_period"], report["evidence_quality"]["line_count"]) == (1, 1, 2)

    def test_other_currencies_never_reach_the_report_and_never_trip_its_currency_mismatch(self):
        report = self.build(run([*shopify_events([order("1")]), *shopify_events([order("2", currency="EUR", subtotal_price="500.00")], source="manual://eur")]).payload)
        assert report["currency"] == "USD" and Decimal(report["revenue"]["amount"]) == Decimal("40")

    def test_hostile_events_cannot_make_the_report_reject_or_leak(self):
        base = shopify_event()
        hostile = [
            Event(base.event_id + "-1", **{**_fields(base), "source": "backend.ecommerce.shopify_readonly\nx"}),
            Event(base.event_id + "-2", **{**_fields(base), "metadata": {**base.metadata, "source": "https://user:pw@shop.example/o?token=abc"}}),
            Event(base.event_id + "-3\x07", **{**_fields(base), "aggregate_id": "9\x00"}),
            Event(base.event_id + "-4", **{**_fields(base), "occurred_at": 1e20}),
        ]
        result = run([*shopify_events([order("1")]), *hostile])
        report = self.build(result.payload)  # would raise OwnerPerformanceReportError("invalid_evidence") before sanitising
        assert report["evidence_quality"]["line_count"] >= 1
        blob = json.dumps({"report": report, "adapter": result.to_dict()})
        for leaked in ("pw@", "token=abc", "shop.example", "\\u0007", "\\u0000"):
            assert leaked not in blob, leaked

    def test_report_safety_and_claims_stay_false_for_ad_spend_and_paid_orders(self):
        events = [
            *shopify_events([order("1")], mode="manual"),
            ledger_event("AdSpendObserved", MARCH_10, channel="meta", amount=15.0, currency="USD", evidence_class="observed"),
            ledger_event("PaymentCaptured", MARCH_10, order_id="1", amount=99.0),
        ]
        report = self.build(run(events).payload)
        assert not any(report["safety"][key] for key in ("ads_launched", "payments_created", "publishing", "launch_authorized", "network_calls", "provider_calls"))
        assert report["campaigns"] == [] and report["evidence_quality"]["claims"]["causal_attribution"] is False and report["evidence_quality"]["claims"]["campaign_lift"] is False
        assert report["ad_spend"]["status"] == "observed", "recorded spend is shown as recorded; it proves neither delivery nor results"
        assert report["realized_profit"]["status"] == "unavailable" and report["evidence_quality"]["claims"]["realized_profit"] is False
