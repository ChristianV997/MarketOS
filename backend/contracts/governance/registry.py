"""governance.registry — register and look up schema versions for artifact types."""
from __future__ import annotations

import threading
from typing import Any

from .schema_version import SchemaVersion, SCHEMA_VERSIONS


class GovernanceRegistry:
    """Thread-safe registry of schema versions and compatibility rules."""

    def __init__(self) -> None:
        self._versions: dict[str, SchemaVersion] = dict(SCHEMA_VERSIONS)
        self._lock = threading.Lock()

    def register(self, artifact_type: str, version: SchemaVersion) -> None:
        with self._lock:
            self._versions[artifact_type] = version

    def current_version(self, artifact_type: str) -> SchemaVersion | None:
        with self._lock:
            return self._versions.get(artifact_type)

    def is_compatible(self, artifact_type: str, version_str: str) -> bool:
        current = self.current_version(artifact_type)
        if current is None:
            return True
        try:
            incoming = SchemaVersion.parse(version_str)
            return current.is_compatible_with(incoming)
        except ValueError:
            return False

    def all_versions(self) -> dict[str, str]:
        with self._lock:
            return {k: str(v) for k, v in self._versions.items()}

    def to_dict(self) -> dict[str, Any]:
        return {"schema_versions": self.all_versions()}


_registry: GovernanceRegistry | None = None
_lock = threading.Lock()


def get_governance_registry() -> GovernanceRegistry:
    global _registry
    if _registry is None:
        with _lock:
            if _registry is None:
                _registry = GovernanceRegistry()
    return _registry
