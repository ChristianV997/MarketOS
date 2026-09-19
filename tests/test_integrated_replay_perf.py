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
    STEPS,
    arbitrate,
    classify_canonical,
    isolated_field_fingerprint,
    live_attestation,
    measure_canonical_scenarios,
    project_event_ids,
    reject_field_hash_as_canonical,
    sanitized_candidates,
)

# Comparable boundary locked by #279 tests/system/test_commercial_dry_run_replay_integration.py
# test_scenario_runs_through_real_builders_and_emits_a_clean_event_trail:
#   event_count == 17 == 1 started + 15 commerce steps + 1 completed.
COMMERCE_LIFECYCLE_EVENT_COUNT = 1 + len(STEPS) + 1  # 17
# #279 scripts/run_commercial_replay_integration.py concatenates
# lifecycle_events + fulfillment_report.events. That CLI trail is 37
# (17 commerce + 20 fulfillment). #274 must not absorb fulfillment.
CLI_COMMERCE_PLUS_FULFILLMENT_EVENT_COUNT = 37


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


def test_commerce_boundary_is_seventeen_not_cli_thirty_seven() -> None:
    assert COMMERCE_LIFECYCLE_EVENT_COUNT == 17
    assert len(STEPS) == 15
    assert CLI_COMMERCE_PLUS_FULFILLMENT_EVENT_COUNT == 37
    assert CLI_COMMERCE_PLUS_FULFILLMENT_EVENT_COUNT - COMMERCE_LIFECYCLE_EVENT_COUNT == 20

    # When canonical imports exist, verify the 17 + 20 = 37 composition and repeat identity
    try:
        from evaluation.commerce.dry_run_events import lifecycle_events
        from evaluation.commerce.dry_run_lifecycle import run_dry_run_lifecycle
        from evaluation.commerce.dry_run_scenarios import hydroponics_positive_candidate
        from evaluation.commerce.fulfillment_risk_lifecycle import (
            FixtureFulfillmentAdapter,
            build_named_scenario,
            run_fulfillment_risk_dry_run,
        )
    except Exception:
        return

    commerce_report = run_dry_run_lifecycle(hydroponics_positive_candidate())
    commerce_events = lifecycle_events(commerce_report, workspace_id="ws-conformance-17")
    assert len(commerce_events) == 17

    fulfillment_scenario = build_named_scenario("customer_return_merchant_paid")
    fulfillment_report = run_fulfillment_risk_dry_run(
        fulfillment_scenario, adapter=FixtureFulfillmentAdapter.complete()
    )
    assert len(fulfillment_report.events) == 20

    combined_events = (*commerce_events, *fulfillment_report.events)
    assert len(combined_events) == 37

    # Repeat run produces identical Event.replay_hash sequences
    commerce_report2 = run_dry_run_lifecycle(hydroponics_positive_candidate())
    commerce_events2 = lifecycle_events(commerce_report2, workspace_id="ws-conformance-17")
    fulfillment_report2 = run_fulfillment_risk_dry_run(
        fulfillment_scenario, adapter=FixtureFulfillmentAdapter.complete()
    )
    combined_events2 = (*commerce_events2, *fulfillment_report2.events)

    hashes1 = [event.replay_hash() for event in combined_events]
    hashes2 = [event.replay_hash() for event in combined_events2]
    assert hashes1 == hashes2
    assert len(hashes1) == 37
    assert all(bool(h) for h in hashes1)

    assert commerce_report.live_actions_taken is False
    assert commerce_report2.live_actions_taken is False


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
        # Commerce-only projection. Do not accept the #279 CLI concat of 37.
        assert row["event_count"] == COMMERCE_LIFECYCLE_EVENT_COUNT
        assert row["event_count"] != CLI_COMMERCE_PLUS_FULFILLMENT_EVENT_COUNT
        assert row["replay_hashes_equal"] is True
        assert row["event_ids_equal"] is True
        assert row["live_actions_taken"] is False
        assert row["live_attestation"] is False
        assert row["hash_authority"] == "Event.replay_hash"
        assert row["execution_class"] == "actual_canonical_dry_run"
        assert row["aggregate_replay_hash_stable"] is True
        assert row["evidence_state_preserved"] is True
        assert "p95_ms" in row and "p99_ms" in row


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
            assert row["event_count"] == COMMERCE_LIFECYCLE_EVENT_COUNT
            assert "p95_ms" in row
            assert "p99_ms" in row
