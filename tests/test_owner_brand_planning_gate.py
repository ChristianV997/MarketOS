"""Tests for the owner brand/site planning inventory gate."""
from __future__ import annotations

import pytest

from backend.commerce.owner_brand_planning_gate import (
    MINIMUM_ELIGIBLE_PRODUCTS,
    evaluate_owner_brand_planning_gate,
)


def _item(product_id, *, eligible=True, status="active"):
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


@pytest.mark.parametrize("count", [1, 2])
def test_one_and_two_eligible_ids_are_blocked(count):
    items = [_item(f"prod-{index}") for index in range(count)]
    gate = evaluate_owner_brand_planning_gate(items)
    assert gate.eligible_count == count
    assert gate.eligible is False
    assert "insufficient_eligible_products" in gate.reasons


def test_three_distinct_eligible_ids_unlock_planning():
    items = [_item("c"), _item("a"), _item("b")]
    gate = evaluate_owner_brand_planning_gate(items)
    assert gate.eligible is True
    assert gate.eligible_count == 3
    assert gate.eligible_product_ids == ("a", "b", "c")
    assert gate.required_count == MINIMUM_ELIGIBLE_PRODUCTS
    assert gate.to_dict()["creates_brand"] is False


def test_duplicates_count_once():
    items = [_item("a"), _item("a"), _item("b"), _item("c")]
    gate = evaluate_owner_brand_planning_gate(items)
    assert gate.eligible_count == 3
    assert "duplicate_id:a" in gate.discarded


def test_malformed_ids_are_discarded():
    items = [_item("ok-1"), {"product_id": "  padded  ", "eligible": True}, {"product_id": "", "eligible": True}, _item("ok-2"), _item("ok-3")]
    gate = evaluate_owner_brand_planning_gate(items)
    assert gate.eligible_product_ids == ("ok-1", "ok-2", "ok-3")
    assert any(item.startswith("malformed_id:") for item in gate.discarded)


def test_ineligible_and_archived_are_not_counted():
    items = [
        _item("live-1"),
        _item("live-2"),
        _item("archived-1", status="archived"),
        _item("paused-1", status="paused"),
        _item("no-flag", eligible=False),
        {"product_id": "unknown-1"},
        _item("live-3"),
    ]
    gate = evaluate_owner_brand_planning_gate(items)
    assert gate.eligible_product_ids == ("live-1", "live-2", "live-3")
    assert "ineligible_status:archived-1" in gate.discarded
    assert "ineligible:no-flag" in gate.discarded
    assert "eligibility_unknown:unknown-1" in gate.discarded


def test_candidate_id_alias_is_accepted():
    items = [
        {"candidate_id": "cand-a", "eligible": True},
        {"candidate_id": "cand-b", "eligible": True},
        {"candidate_id": "cand-c", "eligible": True},
    ]
    gate = evaluate_owner_brand_planning_gate(items)
    assert gate.eligible_product_ids == ("cand-a", "cand-b", "cand-c")


def test_output_is_deterministic():
    items = [_item("z"), _item("m"), _item("a")]
    first = evaluate_owner_brand_planning_gate(items).to_dict()
    second = evaluate_owner_brand_planning_gate(list(reversed(items))).to_dict()
    assert first["eligible_product_ids"] == second["eligible_product_ids"] == ["a", "m", "z"]
