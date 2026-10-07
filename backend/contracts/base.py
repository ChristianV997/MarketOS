"""BaseArtifact — root dataclass for all typed cross-system artifacts.

Every artifact produced by MarketOS or its connected repositories carries:
  - artifact_id: random (UUID4) when a new artifact is created, then persisted
    and preserved; an explicitly supplied id is never replaced or recomputed
  - full lineage chain (parent_ids list)
  - workspace ownership
  - creation timestamp
  - schema version for forward-compatibility

Artifact implementations subclass this and add domain fields.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any


_SCHEMA_VERSION = 1


@dataclass
class BaseArtifact:
    """Abstract base for all typed artifacts."""

    artifact_id:    str              = field(default="")
    artifact_type:  str              = field(default="base")
    workspace:      str              = field(default="default")
    parent_ids:     list[str]        = field(default_factory=list)
    created_at:     float            = field(default_factory=time.time)
    schema_version: int              = field(default=_SCHEMA_VERSION)
    metadata:       dict[str, Any]   = field(default_factory=dict)
    replay_hash:    str              = field(default="")

    def __post_init__(self) -> None:
        if not self.artifact_id:
            self.artifact_id = self._mint_id()
        if not self.replay_hash:
            self.replay_hash = self._derive_replay_hash()

    # ── identity ──────────────────────────────────────────────────────────────

    def _mint_id(self) -> str:
        """Mint the identity of a newly created artifact.

        Identity semantics:

        * New record (no ``artifact_id``): a random UUID4, drawn from the OS
          entropy source, minted once here and persisted by ``to_dict``. It is
          unique across threads, processes, restarts, PID reuse and equal
          timestamps because it carries no process-local state.
        * Stored record (``artifact_id`` present, including replay and
          ``from_dict`` of a serialized artifact): the id is preserved exactly.
          Registering the same id again replaces the earlier version.
        * A payload with no ``artifact_id`` has no persisted identity, so it is
          a new record and receives a fresh id each time it is built. Retrying
          a logical operation is therefore only idempotent when the caller
          supplies a stable ``artifact_id`` of its own.
        """
        return str(uuid.uuid4())

    def _derive_replay_hash(self) -> str:
        """Hash of the serialized record, including its artifact_id."""
        content = json.dumps(self.to_dict(), sort_keys=True, default=str)
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    # ── serialization ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id":    self.artifact_id,
            "artifact_type":  self.artifact_type,
            "workspace":      self.workspace,
            "parent_ids":     self.parent_ids,
            "created_at":     self.created_at,
            "schema_version": self.schema_version,
            "metadata":       self.metadata,
            "replay_hash":    self.replay_hash,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "BaseArtifact":
        # Subclasses are dataclasses too. Recreate them through their public
        # constructor so restored artifacts retain domain fields such as
        # campaign_id and outcome_recorded, not merely BaseArtifact fields.
        if is_dataclass(cls):
            valid_fields = {item.name for item in fields(cls)}
            return cls(**{key: value for key, value in d.items() if key in valid_fields})
        obj = cls.__new__(cls)
        obj.artifact_id    = d.get("artifact_id", "")
        obj.artifact_type  = d.get("artifact_type", "base")
        obj.workspace      = d.get("workspace", "default")
        obj.parent_ids     = d.get("parent_ids", [])
        obj.created_at     = d.get("created_at", time.time())
        obj.schema_version = d.get("schema_version", _SCHEMA_VERSION)
        obj.metadata       = d.get("metadata", {})
        obj.replay_hash    = d.get("replay_hash", "")
        return obj

    def is_valid(self) -> bool:
        return bool(self.artifact_id and self.artifact_type)

    def lineage_chain(self) -> list[str]:
        """Return [*parent_ids, self.artifact_id] — the full ancestry path."""
        return [*self.parent_ids, self.artifact_id]
