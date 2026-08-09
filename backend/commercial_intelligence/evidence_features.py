from __future__ import annotations
import time, uuid
from dataclasses import dataclass, field
from typing import Any

SIGNALS = {"demand", "trend", "competition", "saturation", "price", "margin", "supplier", "creative", "customer", "seasonality", "validation", "risk"}

def _bound(value, low=0.0, high=100.0):
    try: return max(low, min(float(value), high))
    except (TypeError, ValueError): return low

@dataclass
class EvidenceFeature:
    feature_id: str
    workspace_id: str
    source_object_id: str
    source_registry: str
    source_type: str
    entity_type: str
    entity_name: str
    signal_type: str
    value: float = 0.0
    normalized_value: float = 0.0
    confidence: float = 0.0
    direction: str = "unknown"
    time_scope: str = "unknown"
    geography: str = "unknown"
    platform: str = "unknown"
    evidence_strength: str = "unknown"
    limitations: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)
    def __post_init__(self):
        self.value = _bound(self.value, -1_000_000, 1_000_000); self.normalized_value = _bound(self.normalized_value); self.confidence = _bound(self.confidence, 0, 1)
        if self.direction not in {"positive", "negative", "neutral", "unknown"}: self.direction = "unknown"
        if self.evidence_strength not in {"weak", "moderate", "strong", "unknown"}: self.evidence_strength = "unknown"
        if not self.provenance: self.confidence = 0.0; self.limitations.append("missing_provenance")
    def to_dict(self): return {k: getattr(self, k) for k in self.__dataclass_fields__}
    @classmethod
    def from_dict(cls, data): return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})

@dataclass
class EvidenceFeatureSet:
    feature_set_id: str
    workspace_id: str
    title: str
    features: list[EvidenceFeature] = field(default_factory=list)
    source_counts: dict[str, int] = field(default_factory=dict)
    signal_counts: dict[str, int] = field(default_factory=dict)
    limitation_summary: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)
    def to_dict(self): return {k: [x.to_dict() for x in v] if k == "features" else v for k, v in ((k, getattr(self, k)) for k in self.__dataclass_fields__)}
    @classmethod
    def from_dict(cls, data):
        data = dict(data); data["features"] = [EvidenceFeature.from_dict(x) for x in data.get("features", [])]; return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})
    def to_markdown(self): return f"# {self.title}\n\nFeatures: `{len(self.features)}`\n\n## Limitations\n\n" + "\n".join(f"- {x}" for x in self.limitation_summary) + "\n\nFeatures are normalized local evidence, not market-size or profitability claims.\n"

def _numeric(value):
    try: return float(value)
    except (TypeError, ValueError): return 0.0

def extract_evidence_features(workspace_id="default", opportunity_id=None, category=None, product_name=None, limit=500):
    from backend.discovery.discovery_registry import get_discovery_registry
    from backend.discovery.opportunity_registry import get_opportunity_registry
    opportunity = get_opportunity_registry().get_opportunity(opportunity_id) if opportunity_id else None
    category = category or (opportunity.category_name if opportunity else None); product_name = product_name or (opportunity.name if opportunity else None)
    records = get_discovery_registry().list_evidence(workspace_id=workspace_id, limit=min(int(limit), 500))
    features=[]; limitations=[]
    for record in records:
        entity = record.entity_name.lower(); wanted = not category and not product_name or (category and (entity == category.lower() or str(record.metadata.get("category", "")).lower() == category.lower())) or (product_name and entity == product_name.lower())
        if not wanted: continue
        signal_map={"demand_proxy":"demand","rank_proxy":"demand","trend_proxy":"trend","competition_proxy":"competition","margin_proxy":"margin","supplier_proxy":"supplier","price_signal":"price","creative_proxy":"creative","audience_proxy":"customer","pain_point":"customer","risk_proxy":"risk","own_store_sales_proxy":"validation"}
        signal=signal_map.get(record.signal_type)
        if not signal: limitations.append(f"unsupported_signal:{record.signal_type}"); continue
        value=_numeric(record.value); normalized=_bound(value if abs(value)<=100 else 50); synthetic=(record.provenance or {}).get("not_real_market_data") is True
        feature_limitations=[]
        if synthetic: feature_limitations.append("synthetic_fixture_not_real_market_data")
        if record.source_type in {"fixture", "local_file"}: feature_limitations.append("local_or_cached_source_not_live")
        features.append(EvidenceFeature("feature_"+uuid.uuid5(uuid.NAMESPACE_URL, record.evidence_id).hex[:16], workspace_id, record.evidence_id, "discovery_registry", record.source_name, "category" if record.entity_type == "category" else "product", record.entity_name, signal, value, normalized, record.confidence, "positive" if value > 0 else "neutral", str(record.metadata.get("timeframe", "unknown")), str(record.metadata.get("region", "unknown")), str(record.metadata.get("platform", record.source_name)), "strong" if record.confidence >= .75 else "moderate" if record.confidence >= .45 else "weak", feature_limitations, {**record.provenance, "evidence_id": record.evidence_id, "source_name": record.source_name}, record.timestamp, {"raw_signal_type": record.signal_type, "weight": record.weight}))
    if not features: limitations.append("no_matching_numeric_or_qualitative_evidence")
    if any(x.limitations for x in features): limitations.extend(y for x in features for y in x.limitations)
    features=features[:max(1,min(int(limit),500))]
    return EvidenceFeatureSet("features_"+uuid.uuid5(uuid.NAMESPACE_URL, f"{workspace_id}:{category}:{product_name}:{len(features)}").hex[:16], workspace_id, "Commercial Evidence Features", features, {s:sum(x.source_type==s for x in features) for s in sorted({x.source_type for x in features})}, {s:sum(x.signal_type==s for x in features) for s in sorted({x.signal_type for x in features})}, sorted(set(limitations)), metadata={"category":category,"product_name":product_name,"opportunity_id":opportunity_id,"evidence_constrained":True})
