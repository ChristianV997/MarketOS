"""Canonical, advisory-only records for no-credential public observations."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from typing import Any


def _safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe(item) for item in value]
    return str(value)


def signal_identifier(source: str, query: str, source_url: str, title: str) -> str:
    content = json.dumps([source, query.strip().lower(), source_url.strip(), title.strip()], separators=(",", ":"), ensure_ascii=False)
    return "public-signal-" + hashlib.sha256(content.encode("utf-8")).hexdigest()[:20]


@dataclass(frozen=True)
class PublicSignal:
    signal_id: str
    source: str
    source_url: str
    observed_at: float
    query: str
    title: str
    description: str
    score: float
    rank: int
    engagement: dict[str, float] = field(default_factory=dict)
    velocity: dict[str, float] = field(default_factory=dict)
    category: str = ""
    tags: list[str] = field(default_factory=list)
    evidence_url: str = ""
    raw_ref: str = ""
    raw_excerpt: str = ""
    attribution: dict[str, Any] = field(default_factory=dict)
    quality: dict[str, Any] = field(default_factory=dict)
    dry_run: bool = True
    advisory: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) and value.strip() for value in (self.signal_id, self.source, self.source_url, self.title)):
            raise ValueError("signal_id, source, source_url, and title are required")
        if not isinstance(self.observed_at, (int, float)) or not math.isfinite(float(self.observed_at)):
            raise ValueError("observed_at must be a finite epoch value")
        if self.rank < 1:
            raise ValueError("rank must be positive")
        object.__setattr__(self, "score", max(0.0, min(1.0, float(self.score))))
        object.__setattr__(self, "observed_at", float(self.observed_at))
        object.__setattr__(self, "engagement", _safe(self.engagement))
        object.__setattr__(self, "velocity", _safe(self.velocity))
        object.__setattr__(self, "attribution", _safe(self.attribution))
        object.__setattr__(self, "quality", _safe(self.quality))
        object.__setattr__(self, "metadata", _safe(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return _safe(asdict(self))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PublicSignal":
        return cls(**data)


@dataclass(frozen=True)
class PublicSignalIngestionResult:
    source: str
    query: str
    status: str
    signals: list[PublicSignal]
    cache_status: str
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    network_used: bool = False
    source_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {**_safe(asdict(self)), "signals": [item.to_dict() for item in self.signals]}
