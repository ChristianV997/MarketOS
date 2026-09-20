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
    verify_altered_sequence_negative_control,
    verify_event_count_negative_control,
    verify_module_not_truncated,
)


def test_seventeen_versus_thirty_seven_scopes_are_not_like_for_like():
    assert COMMERCE_LIFECYCLE_EVENT_COUNT == 17
    assert CLI_CONCAT_EVENT_COUNT == 37
    assert classify_event_scope(17) == "commerce_lifecycle"
    assert classify_event_scope(37) == "cli_concat_commerce_plus_fulfillment"
    assert classify_event_scope(16) == "unexpected"
    assert classify_event_scope(0) == "unexpected"


def test_event_count_negative_control():
    assert verify_event_count_negative_control(17, "commerce_lifecycle") is True
    assert verify_event_count_negative_control(37, "commerce_lifecycle") is False
    assert verify_event_count_negative_control(16, "commerce_lifecycle") is False


def test_altered_sequence_negative_control():
    seq1 = ["hash_a", "hash_b", "hash_c"]
    seq2 = ["hash_a", "hash_tampered", "hash_c"]
    seq3 = ["hash_b", "hash_a", "hash_c"]
    assert verify_altered_sequence_negative_control(seq1, seq2) is True
    assert verify_altered_sequence_negative_control(seq1, seq3) is True
    assert verify_altered_sequence_negative_control(seq1, seq1) is False


def test_module_not_truncated_check():
    placeholder = "PLACEHOLDER: LAB_RESTORE_REQUIRED = True"
    assert verify_module_not_truncated(placeholder) is False
    assert verify_module_not_truncated("short text") is False
    valid_text = "class ScenarioReplayLaboratory:\n    pass\nclass SensitivityMatrixLaboratory:\n    pass\n" + "\n" * 900
    assert verify_module_not_truncated(valid_text) is True


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
