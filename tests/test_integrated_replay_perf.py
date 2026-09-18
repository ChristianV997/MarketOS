from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.perf.integrated_replay import (
    IntegratedReplayPerfError,
    MAX_CANDIDATES,
    detect_conflicts_indexed,
    detect_conflicts_pairwise,
    hash_events_fields,
    hash_events_json,
    live_attestation,
    measure_size,
    normalize,
    project_events,
    sanitized_candidates,
)
from scripts.run_integrated_replay_perf import build_report


def test_replay_identity_stable_across_repeats() -> None:
    first = measure_size(24, repeats=2)
    second = measure_size(24, repeats=2)
    assert first["replay_identity"] == second["replay_identity"]
    assert first["replay_stable"] is True
    assert first["live_attestation"] is False
    assert "fixture" in first["evidence_states"]


def test_conflict_algorithms_agree() -> None:
    rows = normalize(sanitized_candidates(32))
    assert detect_conflicts_pairwise(rows) == detect_conflicts_indexed(rows)
    assert detect_conflicts_indexed(rows)


def test_event_ids_and_evidence_preserved() -> None:
    rows = normalize(sanitized_candidates(8))
    copied = project_events(rows, copy_metadata=True)
    shared = project_events(rows, copy_metadata=False)
    assert [event["id"] for event in copied] == [event["id"] for event in shared]
    evidence = [event["payload"].get("evidence_state") for event in shared if "evidence_state" in event["payload"]]
    assert "fixture" in evidence
    assert all(event["metadata"]["dry_run"] is True for event in shared)
    assert all(event["metadata"]["no_payment_authority"] is True for event in shared)


def test_fixture_states_cannot_upgrade_live() -> None:
    rows = sanitized_candidates(10)
    assert live_attestation(rows) is False
    assert measure_size(10)["live_attestation"] is False


def test_bounds_reject_oversized_input() -> None:
    with pytest.raises(IntegratedReplayPerfError, match="candidate bound"):
        sanitized_candidates(MAX_CANDIDATES + 1)
    with pytest.raises(IntegratedReplayPerfError, match="size must"):
        sanitized_candidates(0)


def test_field_hash_is_deterministic_and_shorter_path() -> None:
    events = project_events(normalize(sanitized_candidates(12)), copy_metadata=False)
    assert hash_events_fields(events) == hash_events_fields(events)
    assert hash_events_json(events) == hash_events_json(events)
    assert len(hash_events_fields(events)) == len(events)


def test_matrix_report_records_required_fields() -> None:
    report = build_report((1, 10))
    matrix = report["matrix"]
    assert matrix["all_replay_stable"] is True
    assert matrix["all_conflicts_equal"] is True
    assert matrix["no_live_upgrade"] is True
    assert report["failure_class"] == "ok"
    for row in matrix["sizes"]:
        assert row["top_bottleneck"]
        assert "before_ms" in row
        assert "after_ms" in row
        assert row["event_count"] == row["size"] * 17
