"""compatibility — schema compatibility checks for artifact round-trips."""
from __future__ import annotations

from typing import Any

from .schema_version import SchemaVersion, SCHEMA_VERSIONS


def check_compatibility(
    artifact_type: str,
    payload_version: str,
) -> tuple[bool, str]:
    """Check whether a payload version is compatible with the current schema.

    Returns (ok, reason).
    """
    current = SCHEMA_VERSIONS.get(artifact_type)
    if current is None:
        return True, "unknown type — skipping check"
    try:
        incoming = SchemaVersion.parse(payload_version)
    except ValueError as e:
        return False, str(e)

    if current.is_compatible_with(incoming):
        return True, "compatible"
    return False, (
        f"{artifact_type} schema {payload_version} incompatible with current "
        f"{current}: major mismatch or newer minor version"
    )


def assert_compatible(artifact_type: str, payload_version: str) -> None:
    ok, reason = check_compatibility(artifact_type, payload_version)
    if not ok:
        raise ValueError(f"Schema incompatibility: {reason}")


def validate_artifact_dict(d: dict[str, Any]) -> tuple[bool, str]:
    """Validate required base fields on a raw artifact dict."""
    for field in ("artifact_id", "artifact_type", "schema_version"):
        if field not in d:
            return False, f"missing required field: {field!r}"
    ok, reason = check_compatibility(d["artifact_type"], d["schema_version"])
    return ok, reason
