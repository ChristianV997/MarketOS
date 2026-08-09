import json
from pathlib import Path

from backend.events.migration_pilot import (
    LEGACY_EVENT_TYPE,
    append_shadow_mode_decision_pilot,
    build_shadow_mode_decision_event,
    canonical_pilot_enabled,
)
from backend.events.repository import InMemoryEventRepository


ROOT = Path("tests/fixtures/event_migration_pilot")


def _legacy_record():
    return json.loads((ROOT / "legacy_only_input.jsonl").read_text())


def test_pilot_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("MARKETOS_CANONICAL_EVENT_PILOT", raising=False)
    assert canonical_pilot_enabled() is False
    repository = InMemoryEventRepository()
    result = append_shadow_mode_decision_pilot(_legacy_record(), repository)
    assert result.to_dict()["enabled"] is False
    assert list(repository.stream()) == []


def test_pilot_environment_gate_is_explicit_and_never_a_feature_flag(monkeypatch):
    monkeypatch.setenv("MARKETOS_CANONICAL_EVENT_PILOT", "1")
    assert canonical_pilot_enabled() is True
    monkeypatch.setenv("MARKETOS_CANONICAL_EVENT_PILOT", "false")
    assert canonical_pilot_enabled() is False
    # Explicit injection wins, keeping tests independent of process state.
    assert canonical_pilot_enabled(explicit=True) is True
    assert canonical_pilot_enabled(explicit=False) is False


def test_enabled_pilot_builds_valid_non_authoritative_event():
    event = build_shadow_mode_decision_event(_legacy_record())
    assert event.event_type == LEGACY_EVENT_TYPE
    assert event.payload["shadow_id"] == "shadow-fixture-001"
    assert event.metadata["migration_pilot"] is True
    assert event.metadata["dry_run"] is True
    assert event.metadata["non_authoritative"] is True
    assert event.workspace_id == "pilot-fixture"
    assert event.replay_hash()


def test_enabled_pilot_appends_only_to_injected_repository():
    repository = InMemoryEventRepository()
    result = append_shadow_mode_decision_pilot(_legacy_record(), repository, enabled=True)
    assert result.enabled and result.attempted and result.appended
    assert repository.get(result.event.event_id) == result.event


def test_missing_repository_is_fail_closed_without_legacy_side_effects():
    result = append_shadow_mode_decision_pilot(_legacy_record(), enabled=True)
    assert result.enabled is True
    assert result.attempted is False
    assert result.error == "repository_not_supplied"


def test_disabled_and_failure_fixture_expectations_are_explicit():
    disabled = json.loads((ROOT / "disabled_pilot_expected.json").read_text())
    failure = json.loads((ROOT / "canonical_failure_expected.json").read_text())
    repository = InMemoryEventRepository()
    result = append_shadow_mode_decision_pilot(_legacy_record(), repository, enabled=False)
    assert result.enabled is disabled["enabled"]
    assert result.attempted is disabled["attempted"]
    assert result.appended is disabled["appended"]
    assert len(list(repository.stream())) == disabled["canonical_event_count"]


class _FailingRepository:
    def append(self, event):
        raise RuntimeError("fixture failure")


def test_failure_result_is_non_raising_and_observable():
    expected = json.loads((ROOT / "canonical_failure_expected.json").read_text())
    result = append_shadow_mode_decision_pilot(_legacy_record(), _FailingRepository(), enabled=True)
    assert result.enabled is expected["enabled"]
    assert result.attempted is expected["attempted"]
    assert result.appended is expected["appended"]
    assert expected["error_contains"] in result.error
