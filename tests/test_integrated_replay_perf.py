from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.perf.integrated_replay import (
    CANONICAL_BUILDERS,
    IntegratedReplayPerfError,
    MAX_CANDIDATES,
    arbitrate,
    classify_canonical,
    isolated_field_fingerprint,
    live_attestation,
    measure_canonical_scenarios,
    project_event_ids,
    reject_field_hash_as_canonical,
    sanitized_candidates,
)


def test_classification_does_not_claim_this_module_is_authority() -> None:
    info = classify_canonical()
    assert info["this_module_authority"] is False
    assert info["hash_authority"].endswith("Event.replay_hash")
    assert "#280" in info["laboratory_owner"]
    assert info["status"] in {"importable", "unavailable"}


def test_fixture_states_cannot_upgrade_live() -> None:
    rows = sanitized_candidates(10)
    assert live_attestation(rows) is False
    assert live_attestation([{"evidence_state": "fixture"}]) is False
    assert live_attestation([{"evidence_state": "observed"}, {"evidence_state": "fixture"}]) is False


def test_bounds_reject_oversized_input() -> None:
    with pytest.raises(IntegratedReplayPerfError, match="candidate bound"):
        sanitized_candidates(MAX_CANDIDATES + 1)
    with pytest.raises(IntegratedReplayPerfError, match="size must"):
        sanitized_candidates(0)


def test_isolated_field_hash_is_rejected_as_canonical_identity() -> None:
    verdict = reject_field_hash_as_canonical()
    assert verdict["field_hash_is_canonical"] is False
    assert verdict["hashes_equal_to_event_replay_hash"] is False
    rows = sanitized_candidates(4)
    first = isolated_field_fingerprint(project_event_ids(rows), ["fixture"] * 4)
    second = isolated_field_fingerprint(project_event_ids(rows), ["fixture"] * 4)
    assert first == second


def test_canonical_measure_classifies_or_proves_five_scenarios() -> None:
    report = measure_canonical_scenarios()
    assert report["field_hash_rejected_as_identity"] is True
    assert report["event_hash_authority"].endswith("Event.replay_hash")
    if report["status"] == "unavailable":
        assert report["scenarios"] == []
        assert report["no_live_upgrade"] is True
        return
    assert report["status"] == "actual"
    assert report["all_replay_stable"] is True
    assert report["all_sequences_clean"] is True
    assert report["no_live_upgrade"] is True
    assert report["no_live_authority"] is True
    names = [row["scenario"] for row in report["scenarios"]]
    assert names == list(CANONICAL_BUILDERS)
    for row in report["scenarios"]:
        assert row["event_count"] >= 17
        assert row["replay_hashes_equal"] is True
        assert row["event_ids_equal"] is True
        assert row["live_actions_taken"] is False
        assert row["hash_authority"] == "Event.replay_hash"


def test_arbitration_report_records_owners_and_does_not_claim_optimization() -> None:
    report = arbitrate()
    assert report["schema"] == "integrated-replay-arbitration-v2"
    assert report["canonical_path"].startswith("#279")
    assert report["laboratory_path"].startswith("#280")
    assert report["optimization_changes_event_replay_hash"] is False
    assert report["second_replay_path"] is False
    assert report["verdict"]["production_optimization_applied"] is False
    assert report["identity_arbitration"]["field_hash_is_canonical"] is False
    assert report["isolated_scale_note"]["survives_event_replay_hash"] is False
    assert report["laboratory_280_readonly"]["touched_in_this_pr"] is False
    assert report["evidence_classification"] in {"unavailable", "actual", "fixture"}
    if report["canonical"]["status"] == "unavailable":
        assert report["measures_real_commercial_replay"] is False
        assert report["evidence_classification"] == "unavailable"
    else:
        assert report["measures_real_commercial_replay"] is True
        assert report["canonical"]["all_replay_stable"] is True
        for row in report["canonical"]["scenarios"]:
            assert "p95_ms" in row
            assert "p99_ms" in row
