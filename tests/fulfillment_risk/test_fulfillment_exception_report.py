"""Adversarial coverage for the offline fulfillment-exception review."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from backend.contracts.events import Event
from backend.economics.kernel import EvidenceRef
from backend.events.repository import InMemoryEventRepository
from evaluation.commerce.fulfillment_exception_report import (
    PROHIBITED_ACTIONS,
    SCHEMA,
    build_failed_delivery_fixture,
    render_markdown,
    review_fixture_queue,
    review_named_fixture,
    review_proposed_path,
    review_scenario,
)
from evaluation.commerce.fulfillment_risk_lifecycle import (
    FixtureFulfillmentAdapter,
    _TRANSITIONS,
    build_named_scenario,
    run_fulfillment_risk_dry_run,
)
from scripts.run_fulfillment_exception_report import main

REVIEWED = "2026-04-01T00:00:00+00:00"
ROOT = Path(__file__).resolve().parents[2]
SECRET = "ghp_" + "abcdefghijklmnopqrstuvwxyz12"


class _ReadOnlyRepo:
    def __init__(self, inner: InMemoryEventRepository) -> None:
        self.inner = inner
        self.appends = 0

    def append(self, event: Event):  # noqa: ANN201
        self.appends += 1
        raise AssertionError("event append is forbidden")

    def append_many(self, events):  # noqa: ANN201
        self.appends += 1
        raise AssertionError("event append is forbidden")

    def get(self, event_id: str):
        return self.inner.get(event_id)

    def stream(self, event_type=None, aggregate_id=None, limit=None):
        return self.inner.stream(event_type=event_type, aggregate_id=aggregate_id, limit=limit)

    def replay(self, since=None, until=None, **filters):
        return self.inner.replay(since=since, until=until, **filters)

    def tail(self, n=100, event_type=None):
        return self.inner.tail(n=n, event_type=event_type)


def _assert_no_action(document: dict) -> None:
    assert document["schema"] == SCHEMA
    assert document["live_action_allowed"] is False
    assert document["financial_fact"] is False
    assert document["risk_score"] is None
    assert document["amounts_omitted"] is True
    assert document["mutations"] == {
        "refunds": False,
        "customer_contacts": False,
        "supplier_orders": False,
        "event_appends": False,
        "order_writes": False,
    }
    assert document["prohibited_actions"] == list(PROHIBITED_ACTIONS)
    encoded = json.dumps(document)
    assert "999" not in encoded
    assert "MXN" not in encoded
    assert SECRET not in encoded
    assert "initiate_refund" not in encoded
    assert "contact_customer" not in encoded


def test_healthy_fixture_is_not_an_exception_and_is_not_observed():
    document = review_named_fixture("successful_direct_shipment", reviewed_at=REVIEWED)
    _assert_no_action(document)
    assert document["attention_required"] is False
    assert document["evidence"]["basis"] == "simulated"
    assert document["evidence"]["freshness"] == "not_observed"
    assert document["next_safe_review_step"] == "treat_as_fixture_not_observed"
    assert document["transition_review"]["valid"] is True
    assert document["event_store"]["appended"] is False
    assert document["event_store"]["comparison"] == "not_consulted"


def test_delayed_fixture_asks_for_a_read_not_a_customer_contact():
    document = review_named_fixture("shipment_delayed", reviewed_at=REVIEWED)
    _assert_no_action(document)
    assert document["attention_required"] is True
    assert document["delivery_risk"] == {"delayed": True, "failed_delivery": False}
    assert "delayed_delivery" in document["attention_reasons"]
    assert document["next_safe_review_step"] == "read_delay_evidence_only"
    assert "customer" not in document["next_safe_review_step"]


def test_failed_delivery_fixture_does_not_authorize_a_refund():
    scenario, adapter = build_failed_delivery_fixture()
    document = review_scenario(scenario, reviewed_at=REVIEWED, adapter=adapter)
    _assert_no_action(document)
    assert document["attention_required"] is True
    assert document["delivery_risk"]["failed_delivery"] is True
    assert document["transition_review"]["valid"] is True
    assert "failed_delivery" in _TRANSITIONS["delayed"]
    assert document["next_safe_review_step"] == "read_failed_delivery_record_only"
    assert "refund_requested" in document["transition_review"]["lifecycle_allowed_next"]
    assert document["transition_review"]["lifecycle_allowed_next_are_not_actions"] is True
    assert "refund" in document["prohibited_actions"]


def test_illegal_edges_are_explained_and_not_advanced():
    skipped = review_proposed_path(("order_received", "delivered"), order_id="order-illegal", reviewed_at=REVIEWED)
    _assert_no_action(skipped)
    assert skipped["attention_required"] is True
    assert skipped["lifecycle_status"] == "not_run"
    assert skipped["transition_review"]["valid"] is False
    assert skipped["transition_review"]["invalid_edges"] == [{
        "from": "order_received",
        "to": "delivered",
        "lifecycle_allowed_next": ["cancelled", "payment_authorized"],
    }]
    assert skipped["next_safe_review_step"] == "stop_and_review_recorded_path_do_not_advance"
    assert skipped["reserve_classifications"] == []

    direct = review_proposed_path(
        (
            "order_received", "payment_authorized", "payment_captured", "supplier_order_drafted",
            "supplier_order_approved", "supplier_order_submitted", "supplier_accepted", "stock_confirmed",
            "tracking_pending", "in_transit", "delivered", "replacement_requested", "replacement_shipped",
            "failed_delivery",
        ),
        order_id="order-replacement-edge",
        reviewed_at=REVIEWED,
    )
    assert direct["transition_review"]["valid"] is False
    replacement_edge = next(
        edge for edge in direct["transition_review"]["invalid_edges"]
        if edge["from"] == "replacement_shipped" and edge["to"] == "failed_delivery"
    )
    assert "failed_delivery" not in _TRANSITIONS["replacement_shipped"]
    assert replacement_edge["lifecycle_allowed_next"] == sorted(_TRANSITIONS["replacement_shipped"])
    assert direct["next_safe_review_step"] == "stop_and_review_recorded_path_do_not_advance"

    closed = review_proposed_path(
        ("order_received", "payment_authorized", "payment_captured", "cancelled", "contribution_reconciled", "delivered"),
        order_id="order-closed",
        reviewed_at=REVIEWED,
    )
    assert closed["transition_review"]["valid"] is False
    assert any(edge["from"] == "contribution_reconciled" and edge["to"] == "delivered" for edge in closed["transition_review"]["invalid_edges"])


def test_return_delay_and_early_chargeback_stay_review_only():
    delay = review_proposed_path(
        ("order_received", "payment_authorized", "payment_captured", "cancelled", "refund_requested"),
        order_id="order-refund-visible",
        reviewed_at=REVIEWED,
    )
    # refund_requested is a legal edge from cancelled, but path-only still must not refund.
    assert delay["transition_review"]["valid"] is True
    assert delay["evidence"]["basis"] == "not_evaluated"
    assert delay["next_safe_review_step"] == "read_refund_or_chargeback_state_do_not_initiate"
    assert delay["attention_required"] is True

    quiet = review_proposed_path(
        ("order_received", "payment_authorized", "payment_captured"),
        order_id="order-path-only",
        reviewed_at=REVIEWED,
    )
    assert quiet["transition_review"]["valid"] is True
    assert quiet["evidence"] == {"basis": "not_evaluated", "freshness": "not_evaluated", "states": []}
    assert quiet["lifecycle_status"] == "not_run"
    assert quiet["attention_required"] is True
    assert quiet["next_safe_review_step"] == "collect_sanitized_evidence_before_any_decision"
    assert quiet["reserve_classifications"] == []

    base = build_named_scenario("shipment_delayed")
    returned = replace(
        base,
        scenario_id="return-delay",
        order_id="order-return-delay",
        state_path=(
            "order_received", "payment_authorized", "payment_captured", "supplier_order_drafted",
            "supplier_order_approved", "supplier_order_submitted", "supplier_accepted", "stock_confirmed",
            "tracking_pending", "in_transit", "delivered", "return_requested", "rma_opened", "return_in_transit", "delayed",
        ),
    )
    document = review_scenario(returned, reviewed_at=REVIEWED, adapter=FixtureFulfillmentAdapter.complete())
    _assert_no_action(document)
    return_edge = next(
        step for step in document["transition_review"]["steps"]
        if step["from"] == "return_in_transit" and step["to"] == "delayed"
    )
    assert "delayed" in _TRANSITIONS["return_in_transit"]
    assert return_edge["valid"] is True
    assert document["transition_review"]["valid"] is True
    assert document["delivery_risk"]["delayed"] is True
    assert document["next_safe_review_step"] == "read_delay_evidence_only"

    early = replace(
        base,
        scenario_id="early-chargeback",
        order_id="order-early-chargeback",
        state_path=("order_received", "payment_authorized", "chargeback_opened"),
    )
    chargeback = review_scenario(early, reviewed_at=REVIEWED, adapter=FixtureFulfillmentAdapter.complete())
    capture_edge = next(
        step for step in chargeback["transition_review"]["steps"]
        if step["from"] == "payment_authorized" and step["to"] == "chargeback_opened"
    )
    assert "chargeback_opened" in _TRANSITIONS["payment_authorized"]
    assert "payment_captured" not in early.state_path
    assert capture_edge["valid"] is True
    assert chargeback["transition_review"]["valid"] is True
    assert chargeback["transition_review"]["current_state"] == "chargeback_opened"
    assert chargeback["next_safe_review_step"] == "read_refund_or_chargeback_state_do_not_initiate"
    assert chargeback["mutations"]["refunds"] is False


def test_tracking_gap_and_missing_route_are_blockers_not_actions():
    tracking = review_named_fixture("tracking_never_arrives", reviewed_at=REVIEWED)
    _assert_no_action(tracking)
    assert tracking["attention_required"] is True
    assert tracking["lifecycle_status"] == "blocked"
    assert "tracking_unavailable" in tracking["attention_reasons"]
    assert tracking["next_safe_review_step"] == "resolve_recorded_blocker_without_external_action"

    missing = review_named_fixture("unsupported_missing_route", reviewed_at=REVIEWED)
    assert missing["lifecycle_status"] == "blocked"
    assert missing["attention_required"] is True


def test_stale_observed_evidence_is_not_a_fresh_financial_fact():
    base = build_named_scenario("successful_direct_shipment")
    stale = EvidenceRef(
        "observed-old",
        source_type="manual",
        extraction_method="manual",
        evidence_state="observed",
        captured_at="2020-01-01T00:00:00+00:00",
        origin="CN",
        destination="MX",
    )
    scenario = replace(base, scenario_id="stale-observed", order_id="order-stale", evidence_refs=(*base.evidence_refs, stale))
    document = review_scenario(scenario, reviewed_at=REVIEWED, adapter=FixtureFulfillmentAdapter.complete(), max_evidence_age_hours=168)
    _assert_no_action(document)
    assert document["evidence"]["basis"] == "mixed"
    assert document["evidence"]["freshness"] == "stale_for_review"
    assert document["attention_required"] is True
    assert document["next_safe_review_step"] == "collect_sanitized_evidence_before_any_decision"
    assert "source_url" not in json.dumps(document["evidence"])


def test_expired_and_future_evidence_fail_closed():
    base = build_named_scenario("successful_direct_shipment")
    expired = EvidenceRef(
        "observed-expired",
        source_type="manual",
        extraction_method="manual",
        evidence_state="observed",
        captured_at="2026-03-31T00:00:00+00:00",
        valid_until="2026-03-01T00:00:00+00:00",
        origin="CN",
        destination="MX",
    )
    future = EvidenceRef(
        "observed-future",
        source_type="manual",
        extraction_method="manual",
        evidence_state="observed",
        captured_at="2027-01-01T00:00:00+00:00",
        origin="CN",
        destination="MX",
    )
    expired_doc = review_scenario(
        replace(base, scenario_id="expired", order_id="order-expired", evidence_refs=(expired,)),
        reviewed_at=REVIEWED,
        adapter=FixtureFulfillmentAdapter.complete(),
    )
    future_doc = review_scenario(
        replace(base, scenario_id="future", order_id="order-future", evidence_refs=(future,)),
        reviewed_at=REVIEWED,
        adapter=FixtureFulfillmentAdapter.complete(),
    )
    assert expired_doc["evidence"]["freshness"] == "expired"
    assert future_doc["evidence"]["freshness"] == "freshness_inconsistent"
    assert expired_doc["attention_required"] is True
    assert future_doc["attention_required"] is True


def test_repository_is_read_and_never_appended():
    scenario = build_named_scenario("successful_direct_shipment")
    adapter = FixtureFulfillmentAdapter.complete()
    projected = run_fulfillment_risk_dry_run(scenario, adapter=adapter, occurred_at=0.0)
    inner = InMemoryEventRepository()
    for event in projected.events:
        inner.append(event)
    guard = _ReadOnlyRepo(inner)
    matched = review_scenario(scenario, reviewed_at=REVIEWED, adapter=adapter, repository=guard)
    assert guard.appends == 0
    assert matched["event_store"]["comparison"] == "matches_projection"
    assert matched["event_store"]["appended"] is False
    assert matched["attention_required"] is False

    conflict_event = replace(projected.events[0], payload={"scenario_id": "changed"})
    conflict_repo = _ReadOnlyRepo(InMemoryEventRepository())
    conflict_repo.inner.append(conflict_event)
    conflict = review_scenario(scenario, reviewed_at=REVIEWED, adapter=adapter, repository=conflict_repo)
    assert conflict_repo.appends == 0
    assert conflict["event_store"]["comparison"] == "conflict"
    assert conflict["attention_required"] is True
    assert conflict["next_safe_review_step"] == "compare_projection_to_stored_event_without_rewrite"
    assert "changed" not in json.dumps(conflict)

    empty = _ReadOnlyRepo(InMemoryEventRepository())
    absent = review_scenario(scenario, reviewed_at=REVIEWED, adapter=adapter, repository=empty)
    assert empty.appends == 0
    assert absent["event_store"]["comparison"] == "not_present"
    assert absent["attention_required"] is False


def test_repository_identity_mismatch_is_fail_closed():
    scenario = build_named_scenario("successful_direct_shipment")
    adapter = FixtureFulfillmentAdapter.complete()
    projected = run_fulfillment_risk_dry_run(scenario, adapter=adapter)
    mismatched = replace(projected.events[0], workspace_id="other-workspace")
    repository = _ReadOnlyRepo(InMemoryEventRepository())
    repository.inner.append(mismatched)

    document = review_scenario(scenario, reviewed_at=REVIEWED, adapter=adapter, repository=repository)

    assert document["event_store"]["comparison"] == "workspace_mismatch"
    assert document["event_store"]["identity_mismatch_count"] >= 1
    assert document["attention_required"] is True
    assert "event_store_workspace_mismatch" in document["attention_reasons"]


def test_non_fixture_adapter_is_rejected_before_port_execution():
    scenario = build_named_scenario("successful_direct_shipment")
    with pytest.raises(ValueError, match="exact fixture fulfillment adapter"):
        review_scenario(scenario, reviewed_at=REVIEWED, adapter=object())


def test_partial_store_and_unreadable_store_need_review():
    scenario = build_named_scenario("shipment_delayed")
    adapter = FixtureFulfillmentAdapter.complete()
    projected = run_fulfillment_risk_dry_run(scenario, adapter=adapter)
    partial = _ReadOnlyRepo(InMemoryEventRepository())
    partial.inner.append(projected.events[0])
    document = review_scenario(scenario, reviewed_at=REVIEWED, adapter=adapter, repository=partial)
    assert document["event_store"]["comparison"] == "partial"
    assert document["attention_required"] is True

    class _Broken:
        def get(self, event_id: str):
            raise RuntimeError("boom " + SECRET)

        def stream(self, **_kwargs):
            raise RuntimeError("boom " + SECRET)

        def append(self, event: Event):
            raise AssertionError("append")

        def append_many(self, events):
            raise AssertionError("append")

        def replay(self, **_kwargs):
            return []

        def tail(self, n=100, event_type=None):
            return []

    broken = review_scenario(scenario, reviewed_at=REVIEWED, adapter=adapter, repository=_Broken())
    assert broken["event_store"]["comparison"] == "unreadable"
    assert SECRET not in json.dumps(broken)
    assert "boom" not in json.dumps(broken)


def test_secret_and_oversized_paths_are_rejected_without_echo():
    with pytest.raises(ValueError, match="unsafe review input") as caught:
        review_proposed_path(("order_received",), order_id=SECRET, reviewed_at=REVIEWED)
    assert SECRET not in str(caught.value)
    with pytest.raises(ValueError, match="unsafe review input"):
        review_proposed_path(("order_received", "<html>"), order_id="order-html", reviewed_at=REVIEWED)
    long_path = review_proposed_path(("order_received",) * 65, order_id="order-long", reviewed_at=REVIEWED)
    assert long_path["transition_review"]["valid"] is False
    assert long_path["transition_review"]["steps"] == []
    assert "path_too_long" in long_path["attention_reasons"]
    with pytest.raises(ValueError, match="timezone"):
        review_named_fixture("shipment_delayed", reviewed_at="2026-04-01T00:00:00")


def test_queue_is_deterministic_and_cli_filters_exceptions(capsys):
    first = review_fixture_queue(reviewed_at=REVIEWED)
    second = review_fixture_queue(reviewed_at=REVIEWED)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert first["attention_count"] >= 1
    assert all(item["live_action_allowed"] is False for item in first["decisions"])
    delayed = next(item for item in first["decisions"] if item["scenario_id"] == "shipment_delayed")
    healthy = next(item for item in first["decisions"] if item["scenario_id"] == "successful_direct_shipment")
    assert delayed["attention_required"] is True
    assert healthy["attention_required"] is False
    assert first["decisions"][0]["attention_required"] is True

    assert main(["--scenario", "shipment_delayed", "--reviewed-at", REVIEWED, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["next_safe_review_step"] == "read_delay_evidence_only"

    assert main(["--path", "order_received,delivered", "--reviewed-at", REVIEWED, "--markdown"]) == 0
    text = capsys.readouterr().out
    assert "stop_and_review_recorded_path_do_not_advance" in text
    assert "not performed" in text
    assert "999" not in text

    assert main(["--all-fixtures", "--reviewed-at", REVIEWED, "--exceptions-only", "--json"]) == 0
    queue = json.loads(capsys.readouterr().out)
    assert queue["filtered_to_exceptions"] is True
    assert queue["decisions"]
    assert all(item["attention_required"] for item in queue["decisions"])

    assert main(["--failed-delivery-fixture", "--reviewed-at", REVIEWED]) == 0
    failed = json.loads(capsys.readouterr().out)
    assert failed["next_safe_review_step"] == "read_failed_delivery_record_only"

    assert main(["--scenario", "shipment_delayed", "--path", "order_received", "--reviewed-at", REVIEWED]) == 2
    usage = json.loads(capsys.readouterr().err)
    assert usage["overall"] == "malformed"
    assert main(["--order-id", SECRET, "--path", "order_received", "--reviewed-at", REVIEWED]) == 2
    error = json.loads(capsys.readouterr().err)
    assert error["overall"] == "malformed"
    assert SECRET not in json.dumps(error)


def test_module_does_not_grow_a_second_authority_or_shopify_refund_path():
    source = (ROOT / "evaluation/commerce/fulfillment_exception_report.py").read_text(encoding="utf-8")
    script = (ROOT / "scripts/run_fulfillment_exception_report.py").read_text(encoding="utf-8")
    combined = source + script
    assert "shopify" not in combined.lower()
    assert "append_report_events" not in combined
    assert "calculate_unit_economics" not in combined
    assert "calculate_offer_economics" not in combined
    assert "_TRANSITIONS" in source
    rendered = render_markdown(review_named_fixture("successful_direct_shipment", reviewed_at=REVIEWED))
    assert "Live action allowed: `false`" in rendered
