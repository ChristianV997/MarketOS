"""backend.experiments.audit_log — thin wrapper over the existing
backend.orchestration.event_store durable audit log. Not a new log file.
"""
from __future__ import annotations

from typing import Any

from backend.orchestration.event_store import event_store, new_workflow_id

from .envelope import CommercialRunEnvelope

_WORKFLOW = "commercial_run_envelope"


def log_transition(envelope: CommercialRunEnvelope, event: str, *, data: dict[str, Any] | None = None) -> str:
    """Append a transition event for *envelope* to event_store and record
    the resulting workflow_id on envelope.audit_log_refs. Never raises."""
    workflow_id = new_workflow_id(prefix="exp")
    try:
        event_store.append(
            workflow_id,
            event,
            workflow=_WORKFLOW,
            step=envelope.status,
            data={
                "experiment_id": envelope.experiment_id,
                "workspace_id": envelope.workspace_id,
                "service_name": envelope.service_name,
                **(data or {}),
            },
        )
        envelope.audit_log_refs.append(workflow_id)
    except Exception:
        pass
    return workflow_id


def transitions_for(envelope: CommercialRunEnvelope) -> list[dict[str, Any]]:
    """Flatten event_store.events_for(wid) for every workflow_id this
    envelope has logged. Never raises."""
    out: list[dict[str, Any]] = []
    for wid in envelope.audit_log_refs:
        try:
            out.extend(event_store.events_for(wid))
        except Exception:
            continue
    return out
