"""Adversarial and scope tests for the #280 laboratory."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from evaluation.commerce.dry_run_lifecycle import LIFECYCLE_STEPS
from scripts.benchmarks.lab_certification import (
    CLI_CONCAT_EVENT_COUNT,
    COMMERCE_LIFECYCLE_EVENT_COUNT,
    MIN_LAB_MODULE_BYTES,
    PR279_CONCAT_MARKER,
    aggregate_replay_hash,
    classify_event_scope,
    classify_evidence,
    evidence_state_must_not_escalate,
    fail_closed_pr279_certification,
    field_hash_negative_control,
    inspect_replay_cli_source,
    percentile_guard,
    unavailable_import_must_not_certify,
    verify_altered_sequence_negative_control,
    verify_event_count_negative_control,
    verify_module_not_truncated,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LAB_PATH = _REPO_ROOT / "scripts" / "benchmarks" / "benchmark_commercial_replay_lab.py"
_CLI_PATH = _REPO_ROOT / "scripts" / "run_commercial_replay_integration.py"
_PR279_SHA = "0dd413969b5c822f0bcbfa1764ea9fb9eecc9a57"


def test_seventeen_versus_thirty_seven_scopes_are_not_like_for_like():
    assert COMMERCE_LIFECYCLE_EVENT_COUNT == 1 + len(LIFECYCLE_STEPS) + 1
    assert COMMERCE_LIFECYCLE_EVENT_COUNT == 17
    assert CLI_CONCAT_EVENT_COUNT == 37
    assert classify_event_scope(17) == "commerce_lifecycle"
    assert classify_event_scope(37) == "cli_concat_commerce_plus_fulfillment"
    assert classify_event_scope(16) == "unexpected"
    assert classify_event_scope(18) == "unexpected"
    assert classify_event_scope(20) == "fulfillment_only"
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
    valid_text = (
        "class ScenarioReplayLaboratory:\n"
        "class SensitivityMatrixLaboratory:\n"
        "class StatisticalComparisonLaboratory:\n"
        "def generate_laboratory_report():\n"
        "percentile_guard\n"
        "commerce_only_cli_not_pr279\n"
        + "\n" * 900
    )
    assert verify_module_not_truncated(valid_text) is True


def test_actual_lab_module_is_complete_not_truncated():
    raw = _LAB_PATH.read_bytes()
    assert len(raw) >= MIN_LAB_MODULE_BYTES
    assert verify_module_not_truncated(raw) is True
    text = raw.decode("utf-8")
    assert "def run_canonical_replay_integration" in text
    assert "commerce_only_cli_not_pr279" in text
    assert text.rstrip().endswith("sys.exit(main())")


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
    assert unavailable_import_must_not_certify("commerce_only_cli_not_pr279", True) is False
    closed = fail_closed_pr279_certification("commerce_only_cli_not_pr279", "unit")
    assert closed["all_invariants_satisfied"] is False
    assert all(value is False for value in closed["invariant_checks"].values())


def test_evidence_state_must_not_escalate():
    assert evidence_state_must_not_escalate("observed") is True
    assert evidence_state_must_not_escalate("fixture") is True
    assert evidence_state_must_not_escalate("live_readonly") is False
    assert classify_evidence("observed") == "observed"
    assert classify_evidence("fixture") == "fixture"
    with pytest.raises(ValueError):
        classify_evidence("live_readonly")


def test_invalid_sample_shape_and_tail_guard():
    with pytest.raises(ValueError):
        percentile_guard([])
    assert percentile_guard([1.0, 2.0, 3.0], 0.99) == 3.0
    assert percentile_guard([1.0, 2.0, 3.0], 0.95) == 3.0


def test_this_branch_cli_is_not_pr279_concat():
    info = inspect_replay_cli_source(_CLI_PATH)
    assert info["status"] == "available"
    assert info["is_pr279_concat"] is True
    assert PR279_CONCAT_MARKER in _CLI_PATH.read_text(encoding="utf-8")


def test_pr279_cli_blob_is_concat_when_present():
    try:
        text = subprocess.check_output(
            ["git", "show", f"{_PR279_SHA}:scripts/run_commercial_replay_integration.py"],
            cwd=_REPO_ROOT,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        pytest.skip("PR #279 blob 0dd4139 is not in this git object store")
    assert PR279_CONCAT_MARKER.encode("utf-8") in text
    assert b"run_fulfillment_risk_dry_run" in text
    assert len(text) > 20000
