"""Adversarial and scope tests that do not require the full laboratory module."""
from __future__ import annotations

import pytest

from scripts.benchmarks.lab_certification import (
    CLI_CONCAT_EVENT_COUNT,
    COMMERCE_LIFECYCLE_EVENT_COUNT,
    aggregate_replay_hash,
    classify_event_scope,
    evidence_state_must_not_escalate,
    field_hash_negative_control,
    percentile_guard,
    unavailable_import_must_not_certify,
)


def test_seventeen_versus_thirty_seven_scopes_are_not_like_for_like():
    assert COMMERCE_LIFECYCLE_EVENT_COUNT == 17
    assert CLI_CONCAT_EVENT_COUNT == 37
    assert classify_event_scope(17) == "commerce_lifecycle"
    assert classify_event_scope(37) == "cli_concat_commerce_plus_fulfillment"
    assert classify_event_scope(16) == "unexpected"
    assert classify_event_scope(0) == "unexpected"


def test_synthetic_field_hash_is_negative_control():
    control = field_hash_negative_control({"event_id": "x", "payload": {"a": 1}})
    assert control.startswith("field-hash:")
    real = aggregate_replay_hash(["abc", "def"])
    assert len(real) == 64
    assert not real.startswith("field-hash:")
    assert real != control


def test_unavailable_import_must_not_certify():
    assert unavailable_import_must_not_certify("unmerged_dependency", False) is True
    assert unavailable_import_must_not_certify("unmerged_dependency", True) is False
    assert unavailable_import_must_not_certify("unavailable", True) is False


def test_evidence_state_must_not_escalate():
    assert evidence_state_must_not_escalate("observed") is True
    assert evidence_state_must_not_escalate("fixture") is True
    assert evidence_state_must_not_escalate("live_readonly") is False


def test_invalid_sample_shape_and_tail_guard():
    with pytest.raises(ValueError):
        percentile_guard([])
    assert percentile_guard([1.0, 2.0, 3.0], 0.99) == 3.0
