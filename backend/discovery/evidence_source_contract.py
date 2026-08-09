from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class EvidenceSourceCapability:
    source_name: str
    source_type: str
    read_only: bool = True
    network_required: bool = False
    credentials_required: bool = False
    mutation_possible: bool = False
    audited: bool = True
    freshness: str = "static"
    allowed_use: list[str] = field(default_factory=list)
    blocked_reasons: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]: return {key: getattr(self, key) for key in self.__dataclass_fields__}
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidenceSourceCapability": return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})


@dataclass
class EvidenceRecord:
    evidence_id: str
    source_name: str
    source_type: str
    entity_type: str
    entity_name: str
    signal_type: str
    value: Any
    weight: float
    confidence: float
    timestamp: float
    provenance: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.provenance:
            self.confidence = 0.0
        self.weight = max(0.0, min(float(self.weight), 1.0))
        self.confidence = max(0.0, min(float(self.confidence), 1.0))
    def to_dict(self) -> dict[str, Any]: return {key: getattr(self, key) for key in self.__dataclass_fields__}
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidenceRecord":
        required = ["evidence_id", "source_name", "source_type", "entity_type", "entity_name", "signal_type", "value", "weight", "confidence", "timestamp", "provenance"]
        missing = [key for key in required if key not in data]
        if missing: raise ValueError("missing_evidence_fields:" + ",".join(missing))
        if not isinstance(data["provenance"], dict) or not data["provenance"]: raise ValueError("evidence_provenance_required")
        return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})


class EvidenceSourceRegistry:
    def __init__(self, path: str | os.PathLike[str] | None = None, capabilities: list[EvidenceSourceCapability] | None = None) -> None:
        self.path = Path(path or os.getenv("MARKETOS_EVIDENCE_SOURCE_STATE", "state/evidence_sources.json"))
        self.sources: dict[str, EvidenceSourceCapability] = {}
        self._lock = threading.RLock()
        for item in capabilities or default_source_capabilities(): self.register_source(item, persist=False)
        self.load()

    def register_source(self, capability: EvidenceSourceCapability, persist: bool = True) -> EvidenceSourceCapability:
        if capability.source_type == "external_live" or capability.network_required or capability.credentials_required or capability.mutation_possible or not capability.audited:
            capability.blocked_reasons = list(dict.fromkeys([*capability.blocked_reasons, "source_not_allowed_in_read_only_phase"]))
        with self._lock: self.sources[capability.source_name] = capability
        if persist: self.save()
        return capability
    def get_source(self, source_name: str) -> EvidenceSourceCapability | None: return self.sources.get(source_name)
    def list_sources(self, include_blocked: bool = True) -> list[EvidenceSourceCapability]:
        return [item for item in self.sources.values() if include_blocked or not item.blocked_reasons]
    def validate_source_safe(self, source_name: str) -> dict[str, Any]:
        source = self.get_source(source_name)
        if source is None: return {"allowed": False, "status": "unknown_source", "blocked_reasons": ["unknown_source"]}
        reasons = list(source.blocked_reasons)
        if source.network_required: reasons.append("network_required")
        if source.credentials_required: reasons.append("credentials_required")
        if source.mutation_possible: reasons.append("mutation_possible")
        if not source.read_only: reasons.append("source_not_read_only")
        return {"allowed": not reasons, "status": "ready" if not reasons else "blocked", "source_name": source_name, "blocked_reasons": list(dict.fromkeys(reasons)), "capability": source.to_dict()}
    def load(self) -> None:
        try:
            if not self.path.exists(): return
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            for value in raw.get("sources", {}).values():
                if isinstance(value, dict): self.sources[value.get("source_name", "")] = EvidenceSourceCapability.from_dict(value)
        except Exception: pass
    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True); temp = self.path.with_suffix(self.path.suffix + ".tmp")
            temp.write_text(json.dumps({"sources": {key: value.to_dict() for key, value in self.sources.items()}}, indent=2, default=str), encoding="utf-8"); temp.replace(self.path)
        except Exception: pass


def default_source_capabilities() -> list[EvidenceSourceCapability]:
    return [
        EvidenceSourceCapability("local_fixture", "fixture", allowed_use=["discovery"]),
        EvidenceSourceCapability("local_dataset", "local_file", allowed_use=["discovery"]),
        EvidenceSourceCapability("persisted_evidence", "internal_report_index", allowed_use=["discovery"]),
        EvidenceSourceCapability("external_live", "external_live", network_required=True, audited=False, freshness="live_unavailable"),
    ]


_singleton: EvidenceSourceRegistry | None = None
_lock = threading.Lock()
def get_evidence_source_registry() -> EvidenceSourceRegistry:
    global _singleton
    if _singleton is None:
        with _lock:
            if _singleton is None: _singleton = EvidenceSourceRegistry()
    return _singleton
