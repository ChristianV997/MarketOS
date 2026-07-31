"""services.product_research.schemas — ProductAuditResult."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProductAuditResult:
    product_name: str
    category: str = "general"
    discovery: dict[str, Any] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)
    supplier: dict[str, Any] | None = None
    pricing: dict[str, Any] = field(default_factory=dict)
    data_provenance: list[dict[str, Any]] = field(default_factory=list)
    recommendation: str = "unknown"
    dry_run: bool = True
    status: str = "ready_for_client_service"
    generated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_name": self.product_name,
            "category": self.category,
            "discovery": self.discovery,
            "validation": self.validation,
            "supplier": self.supplier,
            "pricing": self.pricing,
            "data_provenance": self.data_provenance,
            "recommendation": self.recommendation,
            "dry_run": self.dry_run,
            "status": self.status,
            "generated_at": self.generated_at,
        }
