"""services.creative_growth.schemas — CreativeGrowthPlan."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CreativeGrowthPlan:
    product_name: str
    category: str = "general"
    hooks: list[str] = field(default_factory=list)
    angles: list[str] = field(default_factory=list)
    hook_matrix: list[dict[str, str]] = field(default_factory=list)
    ugc_briefs: list[dict[str, Any]] = field(default_factory=list)
    content_calendar: dict[str, Any] = field(default_factory=dict)
    fatigue_report: dict[str, Any] = field(default_factory=dict)
    next_batch_recommendation: dict[str, Any] = field(default_factory=dict)
    dry_run: bool = True
    generated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_name": self.product_name,
            "category": self.category,
            "hooks": self.hooks,
            "angles": self.angles,
            "hook_matrix": self.hook_matrix,
            "ugc_briefs": self.ugc_briefs,
            "content_calendar": self.content_calendar,
            "fatigue_report": self.fatigue_report,
            "next_batch_recommendation": self.next_batch_recommendation,
            "dry_run": self.dry_run,
            "generated_at": self.generated_at,
        }
