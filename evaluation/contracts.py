"""Stable, vendor-neutral records consumed by the evaluation layer."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

def _now() -> datetime:
    return datetime.now(timezone.utc)

@dataclass(frozen=True)
class DataQuality:
    provenance: str = "unknown"
    attribution: str = "unknown"
    completeness: str = "complete"
    observed_at: datetime = field(default_factory=_now)
    source_ref: str = ""
    @property
    def is_synthetic(self) -> bool:
        return self.provenance in {"mock", "simulated", "fallback"}
    @property
    def is_live_attributed(self) -> bool:
        return self.provenance == "live" and self.attribution == "attributed"

@dataclass(frozen=True)
class ProductCandidate:
    product_id: str
    name: str
    currency: str = "USD"
    selling_price: float = 0.0
    source_signal_ids: tuple[str, ...] = ()
    quality: DataQuality = field(default_factory=DataQuality)

@dataclass(frozen=True)
class SupplierOffer:
    supplier_id: str
    product_id: str
    unit_cost: float
    shipping_cost: float = 0.0
    fulfillment_days: int | None = None
    inventory_units: int | None = None
    currency: str = "USD"
    quality: DataQuality = field(default_factory=DataQuality)

@dataclass(frozen=True)
class CreativeCandidate:
    creative_id: str
    product_id: str
    hook: str = ""
    angle: str = ""
    script: str = ""
    cta: str = ""
    quality: DataQuality = field(default_factory=DataQuality)

@dataclass(frozen=True)
class CampaignCandidate:
    campaign_id: str
    product_id: str
    creative_id: str = ""
    platform: str = ""
    budget: float = 0.0
    currency: str = "USD"
    quality: DataQuality = field(default_factory=DataQuality)

@dataclass(frozen=True)
class CampaignObservation:
    observation_id: str
    campaign_id: str
    product_id: str = ""
    creative_id: str = ""
    spend: float = 0.0
    revenue: float = 0.0
    impressions: int = 0
    clicks: int = 0
    conversions: int = 0
    refunds: float = 0.0
    currency: str = "USD"
    quality: DataQuality = field(default_factory=DataQuality)
    metadata: dict[str, Any] = field(default_factory=dict)
