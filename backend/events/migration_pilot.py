"""Default-off, non-authoritative canonical mirror for one shadow journal.

The pilot deliberately supports only ``shadow_mode_decision``.  Its legacy
workflow JSONL write remains authoritative; this helper neither reads nor
changes feature flags beyond its own default-off mirror switch.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from backend.contracts.events import Event

from .repository import AppendResult, EventRepository

PILOT_NAME = "shadow_mode_decision_dual_write"
PILOT_ENVIRONMENT_VARIABLE = "MARKETOS_CANONICAL_EVENT_PILOT"
LEGACY_PATH = "backend.deployment.shadow_mode:ShadowModeController.record_shadow_decision"
LEGACY_EVENT_TYPE = "shadow_mode_decision"

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PilotWriteResult:
    enabled: bool
    attempted: bool
    appended: bool
    event: Event | None = None
    append_result: AppendResult | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "attempted": self.attempted,
            "appended": self.appended,
            "event_id": self.event.event_id if self.event else None,
            "replay_hash": self.event.replay_hash() if self.event else None,
            "error": self.error,
        }


def canonical_pilot_enabled(explicit: bool | None = None) -> bool:
    """The mirror is disabled unless explicitly injected or enabled for a test."""
    if explicit is not None:
        return bool(explicit)
    return os.getenv(PILOT_ENVIRONMENT_VARIABLE, "0").strip().lower() in {"1", "true", "yes", "on"}


def build_shadow_mode_decision_event(legacy_record: dict[str, Any]) -> Event:
    """Normalize one already-written legacy shadow decision without mutation."""
    if legacy_record.get("event") != LEGACY_EVENT_TYPE:
        raise ValueError(f"pilot accepts only {LEGACY_EVENT_TYPE!r}")
    data = dict(legacy_record.get("data") or {})
    timestamp = float(legacy_record.get("ts", 0.0) or 0.0)
    workflow_id = str(legacy_record.get("workflow_id") or "shadow-mode")
    shadow_id = str(data.get("shadow_id") or workflow_id)
    workspace_id = data.get("workspace_id")
    if workspace_id is not None:
        workspace_id = str(workspace_id)
    return Event(
        event_id=f"pilot:shadow_mode_decision:{shadow_id}:{timestamp:.6f}",
        workspace_id=workspace_id,
        aggregate_type="shadow_mode_decision",
        aggregate_id=shadow_id,
        event_type=LEGACY_EVENT_TYPE,
        schema_version=1,
        occurred_at=timestamp,
        causation_id=workflow_id,
        correlation_id=workflow_id,
        experiment_id=str(data["experiment_id"]) if data.get("experiment_id") is not None else None,
        actor="shadow_mode_controller",
        source="backend.deployment.shadow_mode",
        payload=data,
        metadata={
            "migration_pilot": True,
            "legacy_path": LEGACY_PATH,
            "legacy_event_type": LEGACY_EVENT_TYPE,
            "dual_write": True,
            "dry_run": True,
            "non_authoritative": True,
            "legacy_workflow": legacy_record.get("workflow", ""),
            "legacy_step": legacy_record.get("step", ""),
        },
    )


def append_shadow_mode_decision_pilot(
    legacy_record: dict[str, Any],
    repository: EventRepository | None = None,
    *,
    enabled: bool | None = None,
) -> PilotWriteResult:
    """Best-effort canonical mirror. It never raises into the legacy caller."""
    active = canonical_pilot_enabled(enabled)
    if not active:
        return PilotWriteResult(enabled=False, attempted=False, appended=False)
    if repository is None:
        return PilotWriteResult(enabled=True, attempted=False, appended=False, error="repository_not_supplied")
    try:
        event = build_shadow_mode_decision_event(legacy_record)
        result = repository.append(event)
        return PilotWriteResult(True, True, result.appended or result.idempotent, event, result)
    except Exception as exc:  # the legacy journal remains the source of truth
        _log.warning("canonical_event_pilot_write_failed event=%s", LEGACY_EVENT_TYPE, exc_info=True)
        return PilotWriteResult(True, True, False, error=f"{type(exc).__name__}: {exc}")
