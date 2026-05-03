"""replay_migration — upgrade older artifact payloads to current schema version."""
from __future__ import annotations

import logging
from typing import Any

from .schema_version import SchemaVersion

log = logging.getLogger(__name__)

# Migration functions keyed by (artifact_type, from_version_str)
_MIGRATIONS: dict[tuple[str, str], Any] = {}


def register_migration(artifact_type: str, from_version: str):
    """Decorator: register a migration function for (type, from_version) → current."""
    def decorator(fn):
        _MIGRATIONS[(artifact_type, from_version)] = fn
        return fn
    return decorator


def migrate(artifact_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Attempt to migrate payload to current schema. Returns payload (possibly updated)."""
    from_version = payload.get("schema_version", "1.0.0")
    key = (artifact_type, from_version)
    fn = _MIGRATIONS.get(key)
    if fn is None:
        return payload
    try:
        migrated = fn(payload)
        log.debug("Migrated %s from %s", artifact_type, from_version)
        return migrated
    except Exception as exc:
        log.warning("Migration failed for %s@%s: %s", artifact_type, from_version, exc)
        return payload


def can_migrate(artifact_type: str, from_version: str) -> bool:
    return (artifact_type, from_version) in _MIGRATIONS
