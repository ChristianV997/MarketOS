import json
from pathlib import Path

from backend.deployment.shadow_mode import ShadowModeController
from backend.events.repository import InMemoryEventRepository
from backend.events.repository import JsonlEventRepository


class CapturingLegacyStore:
    def __init__(self):
        self.records = []

    def append(self, workflow_id, event, *, workflow="", step="", data=None):
        record = {"ts": 1700003000.0, "workflow_id": workflow_id, "workflow": workflow, "step": step, "event": event, "data": data or {}}
        self.records.append(record)
        return record


class FailingRepository:
    def append(self, event):
        raise RuntimeError("synthetic canonical repository failure")


def _record(controller):
    return controller.record_shadow_decision("creative_score", "hold", 0.42, 0.5, "hold", 0.48, 0.55, "synthetic-product")


def test_enabled_dual_write_preserves_legacy_journal(monkeypatch):
    import backend.deployment.shadow_mode as shadow_module

    legacy = CapturingLegacyStore()
    monkeypatch.setattr(shadow_module, "event_store", legacy)
    repository = InMemoryEventRepository()
    controller = ShadowModeController(repository, canonical_pilot_enabled=True)
    _record(controller)
    assert len(legacy.records) == 1
    assert legacy.records[0]["event"] == "shadow_mode_decision"
    assert len(list(repository.stream())) == 1
    assert controller.last_canonical_pilot_result.appended is True


def test_disabled_pilot_keeps_legacy_only(monkeypatch):
    import backend.deployment.shadow_mode as shadow_module

    legacy = CapturingLegacyStore()
    monkeypatch.setattr(shadow_module, "event_store", legacy)
    repository = InMemoryEventRepository()
    controller = ShadowModeController(repository, canonical_pilot_enabled=False)
    _record(controller)
    assert len(legacy.records) == 1
    assert list(repository.stream()) == []
    assert controller.last_canonical_pilot_result.enabled is False


def test_canonical_failure_never_breaks_authoritative_legacy_append(monkeypatch):
    import backend.deployment.shadow_mode as shadow_module

    legacy = CapturingLegacyStore()
    monkeypatch.setattr(shadow_module, "event_store", legacy)
    controller = ShadowModeController(FailingRepository(), canonical_pilot_enabled=True)
    decision = _record(controller)
    assert decision.decision_type == "creative_score"
    assert len(legacy.records) == 1
    assert controller.last_canonical_pilot_result.appended is False
    assert "RuntimeError" in controller.last_canonical_pilot_result.error


def test_pilot_can_use_an_explicit_local_jsonl_repository_in_a_test(monkeypatch, tmp_path):
    """The production controller has no default repository; tests may inject one."""
    import backend.deployment.shadow_mode as shadow_module

    legacy = CapturingLegacyStore()
    monkeypatch.setattr(shadow_module, "event_store", legacy)
    repository = JsonlEventRepository(tmp_path / "canonical-pilot.jsonl")
    controller = ShadowModeController(repository, canonical_pilot_enabled=True)
    _record(controller)
    reloaded = JsonlEventRepository(tmp_path / "canonical-pilot.jsonl")
    canonical = list(reloaded.stream())
    assert len(legacy.records) == 1
    assert len(canonical) == 1
    assert canonical[0].metadata["non_authoritative"] is True
    assert canonical[0].metadata["dry_run"] is True
