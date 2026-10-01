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
import random
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
    assert coverage["claims"] == {"campaign_lift": False, "causal_attribution": False, "live_platform_validated": False, "observed_class_produced": False}
    assert coverage["safety"] == {"read_only": True, "network_calls": False, "provider_calls": False, "mutated": False}
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
