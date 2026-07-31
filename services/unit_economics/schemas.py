"""services.unit_economics.schemas — UnitEconomicsResult."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class UnitEconomicsResult:
    product_name: str
    category: str = "general"
    base_margin: dict[str, Any] = field(default_factory=dict)
    geo_margin: dict[str, Any] | None = None
    ltv_adjusted_margin: dict[str, Any] = field(default_factory=dict)
    break_even_cac: float = 0.0
    required_roas: float = 0.0
    effective_cac: float = 0.0
    scenarios: list[dict[str, Any]] = field(default_factory=list)
    verdict: str = "unknown"
    dry_run: bool = True
    generated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_name": self.product_name,
            "category": self.category,
            "base_margin": self.base_margin,
            "geo_margin": self.geo_margin,
            "ltv_adjusted_margin": self.ltv_adjusted_margin,
            "break_even_cac": self.break_even_cac,
            "required_roas": self.required_roas,
            "effective_cac": self.effective_cac,
            "scenarios": self.scenarios,
            "verdict": self.verdict,
            "dry_run": self.dry_run,
            "generated_at": self.generated_at,
        }
