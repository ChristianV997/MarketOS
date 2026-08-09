from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SourceUsefulnessSignal:
    signal_id: str
    workspace_id: str
    source_name: str
    source_type: str
    parser_type: str
    related_import_id: str = ""
    baseline_discovery_id: str = ""
    current_discovery_id: str = ""
    comparison_id: str = ""
    signal_type: str = ""
    entity_type: str = "category"
    entity_name: str = ""
    value: float = 0.0
    weight: float = 1.0
    confidence: float = 0.5
    rationale: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)
    def __post_init__(self): self.weight = max(0.0, min(float(self.weight), 1.0)); self.confidence = max(0.0, min(float(self.confidence), 1.0)); self.value = float(self.value)
    def to_dict(self): return {key: getattr(self, key) for key in self.__dataclass_fields__}
    @classmethod
    def from_dict(cls, data): return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})


@dataclass
class SourceCalibrationProfile:
    profile_id: str
    workspace_id: str
    source_name: str
    source_type: str
    parser_type: str
    usefulness_score: float = 50.0
    confidence_multiplier_adjustment: float = 1.0
    recommended_priority_adjustment: float = 0.0
    positive_signal_count: int = 0
    negative_signal_count: int = 0
    neutral_signal_count: int = 0
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    best_signal_types: list[str] = field(default_factory=list)
    poor_signal_types: list[str] = field(default_factory=list)
    last_updated_at: float = field(default_factory=time.time)
    provenance: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    def __post_init__(self):
        self.usefulness_score = max(0.0, min(float(self.usefulness_score), 100.0)); self.confidence_multiplier_adjustment = max(0.25, min(float(self.confidence_multiplier_adjustment), 1.25)); self.recommended_priority_adjustment = max(-25.0, min(float(self.recommended_priority_adjustment), 25.0))
    def to_dict(self): return {key: getattr(self, key) for key in self.__dataclass_fields__}
    @classmethod
    def from_dict(cls, data): return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})


@dataclass
class CalibrationRun:
    calibration_id: str
    workspace_id: str
    title: str
    objective: str
    signals: list[SourceUsefulnessSignal] = field(default_factory=list)
    profiles: list[SourceCalibrationProfile] = field(default_factory=list)
    summary: str = ""
    recommendations: list[str] = field(default_factory=list)
    status: str = "completed"
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)
    def to_dict(self): return {key: [x.to_dict() for x in value] if key in {"signals", "profiles"} else value for key, value in ((key, getattr(self, key)) for key in self.__dataclass_fields__)}
    @classmethod
    def from_dict(cls, data):
        data = dict(data); data["signals"] = [SourceUsefulnessSignal.from_dict(x) for x in data.get("signals", [])]; data["profiles"] = [SourceCalibrationProfile.from_dict(x) for x in data.get("profiles", [])]; return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})
    def to_markdown(self):
        rows = "\n".join(f"- **{p.source_name} / {p.parser_type}** — usefulness `{p.usefulness_score:.1f}`, priority adjustment `{p.recommended_priority_adjustment:+.1f}`, strengths: {', '.join(p.strengths) or 'none'}, weaknesses: {', '.join(p.weaknesses) or 'none'}" for p in self.profiles) or "- No calibrated profiles available."
        return f"# {self.title}\n\n**Status:** `{self.status}`  \n**Summary:** {self.summary}\n\n## Profiles\n\n{rows}\n\n## Recommendations\n\n" + "\n".join(f"- {x}" for x in self.recommendations) + "\n\n## Interpretation\n\nThese profiles describe observed changes after evidence inclusion. They are not causal claims and do not prove that a source improved a market or category.\n"


def _signal_sign(signal_type: str) -> float:
    return {"evidence_count_increase": 1, "confidence_increase": 1, "gap_reduction": 1, "rank_improvement": 1, "recommendation_upgrade": 1, "risk_reduction": 1, "duplicate_noise": -1, "low_confidence_noise": -1, "unsupported_signal_rejection": -1}.get(signal_type, 0)


def build_source_calibration_profiles(signals: list[SourceUsefulnessSignal], existing_profiles: list[SourceCalibrationProfile] | None = None) -> list[SourceCalibrationProfile]:
    groups: dict[tuple[str, str, str], list[SourceUsefulnessSignal]] = {}
    for signal in signals: groups.setdefault((signal.workspace_id, signal.source_name, signal.parser_type), []).append(signal)
    profiles = []
    for key, items in sorted(groups.items()):
        positive = sum(_signal_sign(x.signal_type) > 0 for x in items); negative = sum(_signal_sign(x.signal_type) < 0 for x in items); neutral = len(items) - positive - negative
        weighted = sum(_signal_sign(x.signal_type) * min(abs(x.value), 25.0) / 25.0 * x.weight * x.confidence for x in items)
        score = max(0.0, min(100.0, 50.0 + weighted * 12.0))
        adjustment = max(-25.0, min(25.0, weighted * 8.0)); multiplier = max(0.25, min(1.25, 1.0 + weighted * 0.03))
        strengths = sorted({x.signal_type for x in items if _signal_sign(x.signal_type) > 0}); weaknesses = sorted({x.signal_type for x in items if _signal_sign(x.signal_type) < 0})
        profiles.append(SourceCalibrationProfile("profile_" + uuid.uuid5(uuid.NAMESPACE_URL, ":".join(key)).hex[:16], key[0], key[1], items[0].source_type, key[2], score, multiplier, adjustment, positive, negative, neutral, strengths, weaknesses, strengths, weaknesses, last_updated_at=max(x.created_at for x in items), provenance={"method": "deterministic_observed_change_aggregation", "non_causal": True}, metadata={"signal_count": len(items)}))
    return profiles
