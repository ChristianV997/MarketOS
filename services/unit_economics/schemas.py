"""services.unit_economics.schemas — UnitEconomicsResult."""
from __future__ import annotations

import hashlib
import json
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
    status: str = "ready_for_client_service"
    generated_at: float = field(default_factory=time.time)
    validation_errors: list[str] = field(default_factory=list)

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
            "status": self.status,
            "generated_at": self.generated_at,
            "validation_errors": list(self.validation_errors),
        }

    def deterministic_fingerprint(self) -> str:
        """Hash economics payload excluding timestamps and run identifiers."""
        payload = {
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
            "status": self.status,
            "validation_errors": list(self.validation_errors),
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()
