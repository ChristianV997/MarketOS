from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.perf.integrated_replay import (
    CANONICAL_BUILDERS,
    CLI_CONCAT_EVENT_COUNT,
    COMMERCE_LIFECYCLE_EVENT_COUNT,
    FULFILLMENT_EVENT_COUNT,
    IntegratedReplayPerfError,
    MAX_CANDIDATES,
    REQUIRED_SYMBOLS,
    STEPS,
    arbitrate,
    classify_canonical,
    describe_event_scopes,
    inspect_replay_cli_source,
    isolated_field_fingerprint,
    live_attestation,
    measure_canonical_scenarios,
    project_event_ids,
    reject_field_hash_as_canonical,
    sanitized_candidates,
)

THIS_CLI = ROOT / "scripts" / "run_commercial_replay_integration.py"
THIS_MODULE = ROOT / "evaluation" / "perf" / "integrated_replay.py"
PR279_CLI_REF = "origin/codex/marketos-commercial-replay-consolidation-v1:scripts/run_commercial_replay_integration.py"
MIN_MODULE_BYTES = 16_000  # refuse truncated placeholders (prior Contents-API stubs)


def _canonical_or_skip() -> None:
    info = classify_canonical()
    if info["status"] != "importable":
        pytest.skip(f"canonical Event path unavailable: {info['missing']}")


def test_classification_does_not_claim_this_module_is_authority() -> None:
    info = classify_canonical()
    assert info["this_module_authority"] is False
    assert info["hash_authority"].endswith("Event.replay_hash")
    assert "#280" in info["laboratory_owner"]
    assert info["this_harness_event_count"] == 17
    assert info["cli_concat_event_count"] == 37
    assert info["status"] in {"importable", "unavailable"}
    if info["status"] == "unavailable":
        assert info["missing"]
        assert info["economics_delegation"] == "unavailable"


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


def test_tempting_synthetic_hash_is_not_event_identity() -> None:
    _canonical_or_skip()
    from evaluation.commerce.dry_run_events import lifecycle_events
    from evaluation.commerce.dry_run_lifecycle import run_dry_run_lifecycle
    from evaluation.commerce.dry_run_scenarios import hydroponics_positive_candidate

    events = lifecycle_events(
        run_dry_run_lifecycle(hydroponics_positive_candidate()),
        workspace_id="ws-synthetic",
        occurred_at=0.0,
    )
    event_hash = events[0].replay_hash()
    tempting = hashlib.sha256(events[0].event_id.encode("utf-8")).hexdigest()
    field = isolated_field_fingerprint([events[0].event_id], ["observed"])
    assert tempting != event_hash
    assert field != event_hash
    assert event_hash == events[0].replay_hash()


def test_module_is_not_a_truncated_success_stub() -> None:
    import evaluation.perf.integrated_replay as module

    blob = THIS_MODULE.read_bytes()
    assert len(blob) >= MIN_MODULE_BYTES
    for name in REQUIRED_SYMBOLS:
        assert hasattr(module, name), f"missing symbol {name} (truncated module)"
        assert name.encode("utf-8") in blob
    info = classify_canonical()
    if info["status"] == "unavailable":
        report = measure_canonical_scenarios()
        assert report["status"] == "unavailable"
        assert report["scenarios"] == []
        assert report["all_replay_stable"] is False


def test_steps_lock_to_lifecycle_authority() -> None:
    from evaluation.commerce.dry_run_lifecycle import LIFECYCLE_STEPS

    assert STEPS == LIFECYCLE_STEPS
    assert COMMERCE_LIFECYCLE_EVENT_COUNT == 1 + len(LIFECYCLE_STEPS) + 1 == 17
    assert CLI_CONCAT_EVENT_COUNT == 37
    assert FULFILLMENT_EVENT_COUNT == 20
    assert CLI_CONCAT_EVENT_COUNT - COMMERCE_LIFECYCLE_EVENT_COUNT == FULFILLMENT_EVENT_COUNT


def test_this_branch_cli_does_not_concat_fulfillment() -> None:
    verdict = inspect_replay_cli_source(THIS_CLI.read_text(encoding="utf-8"))
    assert verdict["concatenates_fulfillment"] is True
    assert verdict["defines_replay_scenario"] is True
    assert verdict["implied_count"] == CLI_CONCAT_EVENT_COUNT


def test_pr279_cli_source_concatenates_seventeen_plus_twenty() -> None:
    try:
        src = subprocess.check_output(
            ["git", "show", PR279_CLI_REF],
            cwd=ROOT,
            timeout=5,
            stderr=subprocess.DEVNULL,
        ).decode("utf-8")
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        pytest.skip(f"#279 CLI ref not readable: {exc}")
    verdict = inspect_replay_cli_source(src)
    assert verdict["concatenates_fulfillment"] is True
    assert verdict["names_customer_return_merchant_paid"] is True
    assert verdict["defines_replay_scenario"] is True
    assert verdict["implied_count"] == CLI_CONCAT_EVENT_COUNT == 37
    assert verdict["second_spine_if_measured_here"] is False


def test_commerce_boundary_is_seventeen_not_cli_thirty_seven() -> None:
    _canonical_or_skip()
    scopes = describe_event_scopes(
        cli_source=THIS_CLI.read_text(encoding="utf-8"),
    )
    assert scopes["observed_commerce_count"] == COMMERCE_LIFECYCLE_EVENT_COUNT == 17
    assert scopes["observed_fulfillment_count"] == FULFILLMENT_EVENT_COUNT == 20
    assert scopes["observed_commerce_count"] + scopes["observed_fulfillment_count"] == 37
    assert scopes["this_harness_measures"] == 17
    assert scopes["duplicates_279_runner"] is False
    assert scopes["observed_commerce_suffixes"][0] == "started"
    assert scopes["observed_commerce_suffixes"][-1] == "completed"
    assert scopes["observed_commerce_suffixes"][1:-1] == list(STEPS)
    assert scopes["this_branch_cli"]["concatenates_fulfillment"] is True


def test_replay_mismatch_is_detected_on_identity() -> None:
    _canonical_or_skip()
    from evaluation.commerce.dry_run_events import lifecycle_events
    from evaluation.commerce.dry_run_lifecycle import run_dry_run_lifecycle
    from evaluation.commerce.dry_run_scenarios import hydroponics_positive_candidate

    first = lifecycle_events(
        run_dry_run_lifecycle(hydroponics_positive_candidate()),
        workspace_id="ws-mismatch-a",
        occurred_at=0.0,
    )
    second = lifecycle_events(
        run_dry_run_lifecycle(hydroponics_positive_candidate()),
        workspace_id="ws-mismatch-a",
        occurred_at=0.0,
    )
    # Same envelope identity must match.
    assert [event.replay_hash() for event in first] == [event.replay_hash() for event in second]
    # occurred_at is part of Event.canonical_json, so hashes must move.
    third = lifecycle_events(
        run_dry_run_lifecycle(hydroponics_positive_candidate()),
        workspace_id="ws-mismatch-a",
        occurred_at=1.0,
    )
    assert [event.replay_hash() for event in first] != [event.replay_hash() for event in third]
    other_ws = lifecycle_events(
        run_dry_run_lifecycle(hydroponics_positive_candidate()),
        workspace_id="ws-mismatch-b",
        occurred_at=0.0,
    )
    assert [event.replay_hash() for event in first] != [event.replay_hash() for event in other_ws]


def test_canonical_measure_classifies_or_proves_five_scenarios() -> None:
    report = measure_canonical_scenarios()
    assert report["field_hash_rejected_as_identity"] is True
    assert report["event_hash_authority"].endswith("Event.replay_hash")
    assert report["this_harness_event_count"] == COMMERCE_LIFECYCLE_EVENT_COUNT
    if report["status"] == "unavailable":
        assert report["scenarios"] == []
        assert report["no_live_upgrade"] is True
        assert report["all_replay_stable"] is False
        return
    assert report["status"] == "actual"
    assert report["all_replay_stable"] is True
    assert report["all_sequences_clean"] is True
    assert report["no_live_upgrade"] is True
    assert report["no_live_authority"] is True
    assert report["environment"]["warmup"] == 1
    assert report["environment"]["repeats"] == 5
    names = [row["scenario"] for row in report["scenarios"]]
    assert names == list(CANONICAL_BUILDERS)
    for row in report["scenarios"]:
        assert row["event_count"] == COMMERCE_LIFECYCLE_EVENT_COUNT
        assert row["event_count"] != CLI_CONCAT_EVENT_COUNT
        assert row["replay_hashes_equal"] is True
        assert row["event_ids_equal"] is True
        assert row["live_actions_taken"] is False
        assert row["live_attestation"] is False
        assert row["hash_authority"] == "Event.replay_hash"
        assert row["execution_class"] == "actual_canonical_dry_run"
        assert row["aggregate_replay_hash_stable"] is True
        assert row["evidence_state_preserved"] is True
        assert row["warmup"] == 1
        assert row["n"] == 5
        assert "p95_ms" in row and "p99_ms" in row
        suffixes = [event_id.split(":")[-1] for event_id in row["event_ids"]]
        assert suffixes == ["started", *STEPS, "completed"]


def test_arbitration_report_records_owners_and_does_not_claim_optimization() -> None:
    report = arbitrate()
    assert report["schema"] == "integrated-replay-arbitration-v2"
    assert report["canonical_path"].startswith("#279")
    assert report["laboratory_path"].startswith("#280")
    assert report["optimization_changes_event_replay_hash"] is False
    assert report["second_replay_path"] is False
    assert report["verdict"]["production_optimization_applied"] is False
    assert report["verdict"]["this_harness_event_count"] == 17
    assert report["identity_arbitration"]["field_hash_is_canonical"] is False
    assert report["isolated_scale_note"]["survives_event_replay_hash"] is False
    assert report["laboratory_280_readonly"]["touched_in_this_pr"] is False
    assert report["event_scopes"]["duplicates_279_runner"] is False
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
