"""Canonical, JSON-safe event envelope for new MarketOS event code.

``occurred_at`` is a UTC epoch float to match existing workflow and replay
stores. Existing event paths are adapted; this module does not replace them.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any


class CanonicalEventError(ValueError):
    """Base error for invalid canonical events."""


class InvalidCanonicalEvent(CanonicalEventError):
    """Raised when required envelope fields or JSON-safe values are invalid."""


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


@dataclass(frozen=True)
class Event:
    event_id: str
    workspace_id: str | None
    aggregate_type: str
    aggregate_id: str
    event_type: str
    schema_version: int
    occurred_at: float
    causation_id: str | None = None
    correlation_id: str | None = None
    experiment_id: str | None = None
    actor: str | None = None
    source: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        required = {"event_id": self.event_id, "aggregate_type": self.aggregate_type, "aggregate_id": self.aggregate_id, "event_type": self.event_type, "source": self.source}
        missing = [name for name, value in required.items() if not isinstance(value, str) or not value.strip()]
        if missing:
            raise InvalidCanonicalEvent(f"required canonical event fields missing: {', '.join(missing)}")
        if not isinstance(self.schema_version, int) or self.schema_version < 1:
            raise InvalidCanonicalEvent("schema_version must be a positive integer")
        if not isinstance(self.occurred_at, (int, float)) or not math.isfinite(float(self.occurred_at)):
            raise InvalidCanonicalEvent("occurred_at must be a finite UTC epoch timestamp")
        if not isinstance(self.payload, dict) or not isinstance(self.metadata, dict):
            raise InvalidCanonicalEvent("payload and metadata must be dictionaries")
        object.__setattr__(self, "occurred_at", float(self.occurred_at))
        object.__setattr__(self, "payload", _json_safe(self.payload))
        object.__setattr__(self, "metadata", _json_safe(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {"event_id": self.event_id, "workspace_id": self.workspace_id, "aggregate_type": self.aggregate_type, "aggregate_id": self.aggregate_id, "event_type": self.event_type, "schema_version": self.schema_version, "occurred_at": self.occurred_at, "causation_id": self.causation_id, "correlation_id": self.correlation_id, "experiment_id": self.experiment_id, "actor": self.actor, "source": self.source, "payload": self.payload, "metadata": self.metadata}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Event":
        if not isinstance(data, dict):
            raise InvalidCanonicalEvent("canonical event must be a dictionary")
        return cls(**{key: data.get(key) for key in cls.__dataclass_fields__})

    def canonical_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)

    def replay_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @classmethod
    def from_workflow_record(cls, record: dict[str, Any]) -> "Event":
        workflow_id = str(record.get("workflow_id") or "legacy-workflow")
        event_name = str(record.get("event") or "legacy.workflow.event")
        return cls(str(record.get("event_id") or f"workflow:{workflow_id}:{record.get('ts', 0)}:{event_name}"), None, "workflow", workflow_id, event_name, 1, float(record.get("ts", 0.0) or 0.0), correlation_id=workflow_id, source="legacy.workflow_event_store", payload=dict(record.get("data") or {}), metadata={"legacy_workflow": record.get("workflow", ""), "legacy_step": record.get("step", ""), "legacy_record": True})

    @classmethod
    def from_pubsub_envelope(cls, envelope: Any) -> "Event":
        payload = dict(getattr(envelope, "payload", {}) or {})
        return cls(str(getattr(envelope, "event_id", "")), payload.pop("workspace_id", None), str(payload.pop("aggregate_type", "runtime")), str(payload.pop("aggregate_id", getattr(envelope, "event_id", ""))), str(getattr(envelope, "type", "")), int(getattr(envelope, "event_version", 1) or 1), float(getattr(envelope, "ts", 0.0) or 0.0), correlation_id=getattr(envelope, "correlation_id", None), source=str(getattr(envelope, "source", "pubsub")), payload=payload, metadata={"legacy_sequence_id": getattr(envelope, "sequence_id", None), "legacy_replay_hash": getattr(envelope, "replay_hash", None)})
