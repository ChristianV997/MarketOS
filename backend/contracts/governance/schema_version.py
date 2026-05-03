"""schema_version — semantic versioning for artifact schemas."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SchemaVersion:
    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    @classmethod
    def parse(cls, version_str: str) -> "SchemaVersion":
        m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version_str.strip())
        if not m:
            raise ValueError(f"Invalid schema version: {version_str!r}")
        return cls(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    def is_compatible_with(self, other: "SchemaVersion") -> bool:
        """Backward-compatible: same major, other.minor <= self.minor."""
        return self.major == other.major and other.minor <= self.minor

    def bump_major(self) -> "SchemaVersion":
        return SchemaVersion(self.major + 1, 0, 0)

    def bump_minor(self) -> "SchemaVersion":
        return SchemaVersion(self.major, self.minor + 1, 0)

    def bump_patch(self) -> "SchemaVersion":
        return SchemaVersion(self.major, self.minor, self.patch + 1)

    def to_dict(self) -> dict[str, Any]:
        return {"major": self.major, "minor": self.minor, "patch": self.patch, "str": str(self)}


# Current schema versions per artifact type
SCHEMA_VERSIONS: dict[str, SchemaVersion] = {
    "base":       SchemaVersion(1, 0, 0),
    "campaign":   SchemaVersion(1, 1, 0),
    "signal":     SchemaVersion(1, 0, 0),
    "playbook":   SchemaVersion(1, 0, 0),
    "pattern":    SchemaVersion(1, 0, 0),
    "trace_span": SchemaVersion(1, 0, 0),
    "entropy_report": SchemaVersion(1, 0, 0),
}
