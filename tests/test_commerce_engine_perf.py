from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from evaluation.perf.commerce_engine import (
    CommerceEnginePerfError,
    detect_conflicts_indexed,
    detect_conflicts_pairwise,
    measure_algorithms,
    process_offers,
)
from scripts.run_commerce_engine_perf import build_rows, run_harness, run_scenario


def test_replay_equality_and_evidence_preservation() -> None:
    rows = build_rows("mixed_evidence", 24)
    first = process_offers(rows)
    second = process_offers(rows)
    assert first.replay_identity == second.replay_identity
    assert first.live_attestation is False
    assert "fixture" in first.evidence_states
    assert first.to_dict()["accepted"][0]["evidence_state"] in {
        "fixture",
        "stale",
        "observed",
        "live_readonly",
        "conflicting",
    }


def test_duplicate_and_conflict_behavior() -> None:
    rows = [
        {"candidate_id": "sku-1", "supplier": "cj", "sku": "A", "currency": "MXN", "unit_cost": "10", "evidence_state": "fixture"},
        {"candidate_id": "sku-1", "supplier": "cj", "sku": "A", "currency": "MXN", "unit_cost": "12", "evidence_state": "fixture"},
    ]
    pairwise = detect_conflicts_pairwise(process_offers(rows).accepted)
    indexed = detect_conflicts_indexed(process_offers(rows).accepted)
    result = process_offers(rows)
    assert pairwise == indexed
    assert result.conflicts
    assert result.failure_class.endswith("conflicting") or result.failure_class == "conflicting"
    assert all(item["evidence_state"] == "conflicting" for item in result.accepted)


def test_malformed_and_secret_rows_are_rejected() -> None:
    rows = [
        "bad",
        {"html": "<!doctype"},
        {"candidate_id": "ok", "currency": "MXN", "unit_cost": "1", "evidence_state": "fixture"},
        {"candidate_id": "x", "api_key": "sk_test_dummy", "currency": "MXN"},
        {"candidate_id": "bad-money", "currency": "MXN", "unit_cost": "not-a-number"},
    ]
    result = process_offers(rows)
    reasons = {item["reason"] for item in result.rejected}
    assert "malformed" in reasons
    assert "secret_shaped" in reasons
    assert "invalid_money" in reasons
    assert result.failure_class.startswith("partial_failure")
    assert len(result.accepted) == 1


def test_mixed_currency_is_isolated_not_converted() -> None:
    rows = [
        {"candidate_id": "a", "currency": "MXN", "unit_cost": "10", "evidence_state": "fixture"},
        {"candidate_id": "b", "currency": "USD", "unit_cost": "10", "evidence_state": "fixture"},
    ]
    result = process_offers(rows)
    assert result.currencies == ("MXN", "USD")
    assert "mixed_currency_isolated" in result.notes
    assert result.live_attestation is False


def test_input_bound_and_payload_limit() -> None:
    rows = build_rows("many_candidates", 40)
    result = process_offers(rows, max_rows=16)
    assert result.row_count_in == 16
    assert any(note.startswith("truncated") for note in result.notes)
    huge = [{"candidate_id": "x", "pad": "n" * 2000, "currency": "MXN"} for _ in range(400)]
    with pytest.raises(CommerceEnginePerfError, match="payload exceeds bound"):
        process_offers(huge)


def test_algorithm_equivalence_and_indexed_not_slower_on_conflict_set() -> None:
    rows = build_rows("many_candidates", 800)
    report = measure_algorithms(rows, repeats=2)
    assert report["equivalence"] is True
    assert report["pairwise_replay_stable"] is True
    assert report["indexed_replay_stable"] is True
    assert report["indexed_mean_ms"] <= report["pairwise_mean_ms"] * 1.5


def test_harness_records_required_fields() -> None:
    report = run_harness(size=32, compare=True)
    assert report["evidence_state"] == "fixture"
    assert report["live_providers"] is False
    assert report["algorithm_comparison"]["equivalence"] is True
    for record in report["scenarios"]:
        assert record["scenario"]
        assert "wall_ms" in record
        assert "repeated_run_equality" in record
        assert "failure_classification" in record
        assert record["live_attestation"] is False
    replay = run_scenario("replay", 20)
    assert replay["repeated_run_equality"] is True


def test_json_roundtrip_stable() -> None:
    result = process_offers(build_rows("nested_variants", 12))
    payload = json.dumps(result.to_dict(), sort_keys=True)
    again = json.dumps(result.to_dict(), sort_keys=True)
    assert payload == again


@pytest.mark.parametrize("size", (10, 100, 1000))
def test_indexed_and_pairwise_conflict_detection_stay_equivalent_at_every_measured_size(size: int) -> None:
    """Mission-required sizes (COMMERCIAL-REPLAY-INTEGRATION-V3 section E):
    output equivalence and replay stability must hold at every measured
    size, not just the PR's original 1,500-row headline figure."""
    rows = build_rows("many_candidates", size)
    result = measure_algorithms(rows, repeats=3)
    assert result["rows"] == size
    assert result["equivalence"] is True
    assert result["pairwise_replay_stable"] is True
    assert result["indexed_replay_stable"] is True
    assert result["indexed_mean_ms"] >= 0 and result["pairwise_mean_ms"] >= 0
