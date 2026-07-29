"""BaseArtifact — root dataclass for all typed cross-system artifacts.

Every artifact produced by MarketOS or its connected repositories carries:
  - deterministic artifact_id (content-addressed)
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
            self.artifact_id = self._derive_id()
        if not self.replay_hash:
            self.replay_hash = self._derive_replay_hash()

    # ── identity ──────────────────────────────────────────────────────────────

    def _derive_id(self) -> str:
        """UUID5 from artifact_type + workspace + key content."""
        key = f"{self.artifact_type}:{self.workspace}:{self.created_at}"
        namespace = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
        return str(uuid.uuid5(namespace, key))

    def _derive_replay_hash(self) -> str:
        """Content-addressed hash for replay deduplication."""
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
