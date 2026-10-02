"""Tests for the owner brand/site planning inventory gate."""
from __future__ import annotations

import pytest

from backend.commerce.owner_brand_planning_gate import (
    MINIMUM_ELIGIBLE_PRODUCTS,
    OwnerBrandPlanningGateError,
    evaluate_owner_brand_planning_gate,
)


def _item(product_id, *, eligible=True, status="live"):
    return {"product_id": product_id, "eligible": eligible, "status": status}


def test_missing_inventory_is_not_zero():
    gate = evaluate_owner_brand_planning_gate(None)
    assert gate.status == "blocked"
    assert gate.eligible_count is None
    assert "inventory_missing" in gate.reasons


def test_empty_inventory_is_zero_and_blocked():
    gate = evaluate_owner_brand_planning_gate([])
    assert gate.eligible_count == 0
    assert gate.eligible is False
    assert "inventory_empty" in gate.reasons


@pytest.mark.parametrize("count", [0, 1, 2, 3])
def test_threshold(count):
    items = [_item(f"prod-{index}") for index in range(count)]
    gate = evaluate_owner_brand_planning_gate(items)
    assert gate.eligible_count == count
    assert gate.eligible is (count >= MINIMUM_ELIGIBLE_PRODUCTS)


def test_three_distinct_eligible_ids_unlock_planning():
    items = [_item("c"), _item("a"), _item("b")]
    gate = evaluate_owner_brand_planning_gate(items)
    payload = gate.to_dict()
    assert gate.eligible is True
    assert gate.eligible_product_ids == ("a", "b", "c")
    assert payload["creates_brand"] is False
    assert payload["publishes"] is False
    assert payload["launches_ads"] is False
    assert payload["planning_only"] is True


def test_exact_duplicates_count_once():
    items = [_item("a"), _item("a"), _item("b"), _item("c")]
    gate = evaluate_owner_brand_planning_gate(items)
    assert gate.eligible_count == 3
    assert gate.eligible_product_ids == ("a", "b", "c")


def test_conflicting_duplicates_do_not_satisfy_threshold():
    items = [
        _item("a"),
        _item("a", status="paused"),
        _item("b"),
        _item("c"),
    ]
    gate = evaluate_owner_brand_planning_gate(items)
    assert gate.eligible is False
    assert gate.eligible_product_ids == ("b", "c")
    assert "duplicate_conflict:a" in gate.discarded


def test_eligible_flag_conflict_does_not_count():
    items = [
        _item("a"),
        _item("a", eligible=False),
        _item("b"),
        _item("c"),
    ]
    gate = evaluate_owner_brand_planning_gate(items)
    assert gate.eligible is False
    assert gate.eligible_product_ids == ("b", "c")
    assert "duplicate_conflict:a" in gate.discarded


def test_only_exact_true_eligibility_counts():
    items = [
        _item("string-true", eligible="true"),
        _item("one", eligible=1),
        _item("ok-1"),
        _item("ok-2"),
        _item("ok-3"),
    ]
    gate = evaluate_owner_brand_planning_gate(items)
    assert gate.eligible_product_ids == ("ok-1", "ok-2", "ok-3")
    assert "ineligible:string-true" in gate.discarded
    assert "ineligible:one" in gate.discarded


def test_status_must_be_exactly_live():
    items = [
        _item("case", status="Live"),
        _item("padded", status=" live"),
        _item("ok-1"),
        _item("ok-2"),
        _item("ok-3"),
    ]
    gate = evaluate_owner_brand_planning_gate(items)
    assert gate.eligible_product_ids == ("ok-1", "ok-2", "ok-3")
    assert "status_not_active:case" in gate.discarded
    assert "status_not_active:padded" in gate.discarded


def test_missing_and_unknown_status_do_not_count():
    items = [
        _item("live-1"),
        _item("live-2"),
        {"product_id": "missing-status", "eligible": True},
        _item("unknown-status", status="active"),
        _item("draft-1", status="draft"),
        _item("live-3"),
    ]
    gate = evaluate_owner_brand_planning_gate(items)
    assert gate.eligible_product_ids == ("live-1", "live-2", "live-3")
    assert "status_missing:missing-status" in gate.discarded
    assert "status_not_active:unknown-status" in gate.discarded
    assert "status_not_active:draft-1" in gate.discarded


def test_malformed_ids_and_types_are_discarded():
    items = [
        _item("ok-1"),
        {"product_id": "  padded  ", "eligible": True, "status": "live"},
        {"product_id": "", "eligible": True, "status": "live"},
        {"product_id": 12, "eligible": True, "status": "live"},
        "not-a-row",
        {"product_id": "split-a", "candidate_id": "split-b", "eligible": True, "status": "live"},
        _item("ok-2"),
        _item("ok-3"),
    ]
    gate = evaluate_owner_brand_planning_gate(items)
    assert gate.eligible_product_ids == ("ok-1", "ok-2", "ok-3")
    assert any(item.startswith("malformed_id:") for item in gate.discarded)
    assert "malformed_row:4" in gate.discarded


def test_non_sequence_inventory_is_rejected():
    with pytest.raises(OwnerBrandPlanningGateError) as caught:
        evaluate_owner_brand_planning_gate({"product_id": "a"})
    assert caught.value.code == "inventory_must_be_sequence"


def test_candidate_id_alias_requires_live_status():
    items = [
        {"candidate_id": "cand-a", "eligible": True, "status": "live"},
        {"candidate_id": "cand-b", "eligible": True, "status": "live"},
        {"candidate_id": "cand-c", "eligible": True, "status": "live"},
    ]
    gate = evaluate_owner_brand_planning_gate(items)
    assert gate.eligible_product_ids == ("cand-a", "cand-b", "cand-c")


def test_output_is_stable_across_permutations():
    items = [_item("z"), _item("m"), _item("a")]
    first = evaluate_owner_brand_planning_gate(items).to_dict()
    second = evaluate_owner_brand_planning_gate(list(reversed(items))).to_dict()
    assert first["eligible_product_ids"] == second["eligible_product_ids"] == ["a", "m", "z"]
    assert first["discarded"] == second["discarded"]
