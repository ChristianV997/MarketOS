from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from .discovery_comparison import DiscoveryComparison
from .evidence_gap import EvidenceGapAnalysis
from .import_recommendation import ImportRecommendationPlan
from .import_templates import ImportTemplate


class RefinementRegistry:
    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self.path = Path(path or os.getenv("MARKETOS_REFINEMENT_STATE", "state/refinement_registry.json")); self.gap_analyses = {}; self.import_plans = {}; self.templates = {}; self.comparisons = {}; self._lock = threading.RLock(); self.load()
    def register_gap_analysis(self, item): self.gap_analyses[item.analysis_id] = item; self.save(); return item
    def get_gap_analysis(self, item_id): return self.gap_analyses.get(item_id)
    def list_gap_analyses(self, workspace_id=None, limit=50): return list(reversed([x for x in self.gap_analyses.values() if workspace_id is None or x.workspace_id == workspace_id]))[:max(0, min(int(limit), 500))]
    def register_import_plan(self, item): self.import_plans[item.plan_id] = item; self.save(); return item
    def get_import_plan(self, item_id): return self.import_plans.get(item_id)
    def list_import_plans(self, workspace_id=None, limit=50): return list(reversed([x for x in self.import_plans.values() if workspace_id is None or x.workspace_id == workspace_id]))[:max(0, min(int(limit), 500))]
    def register_template(self, item): self.templates[item.template_id] = item; self.save(); return item
    def get_template(self, item_id): return self.templates.get(item_id)
    def list_templates(self, parser_type=None, limit=100): return [x for x in self.templates.values() if parser_type is None or x.parser_type == parser_type][:max(0, min(int(limit), 500))]
    def register_comparison(self, item): self.comparisons[item.comparison_id] = item; self.save(); return item
    def get_comparison(self, item_id): return self.comparisons.get(item_id)
    def list_comparisons(self, workspace_id=None, limit=50): return list(reversed([x for x in self.comparisons.values() if workspace_id is None or x.workspace_id == workspace_id]))[:max(0, min(int(limit), 500))]
    def clear_for_tests(self): self.gap_analyses.clear(); self.import_plans.clear(); self.templates.clear(); self.comparisons.clear(); self.save()
    def to_dict(self): return {"gap_analyses": {k: v.to_dict() for k, v in self.gap_analyses.items()}, "import_plans": {k: v.to_dict() for k, v in self.import_plans.items()}, "templates": {k: v.to_dict() for k, v in self.templates.items()}, "comparisons": {k: v.to_dict() for k, v in self.comparisons.items()}}
    def load(self):
        try:
            if not self.path.exists(): return
            raw = json.loads(self.path.read_text(encoding="utf-8")); self.gap_analyses = {k: EvidenceGapAnalysis.from_dict(v) for k, v in raw.get("gap_analyses", {}).items()}; self.import_plans = {k: ImportRecommendationPlan.from_dict(v) for k, v in raw.get("import_plans", {}).items()}; self.templates = {k: ImportTemplate.from_dict(v) for k, v in raw.get("templates", {}).items()}; self.comparisons = {k: DiscoveryComparison.from_dict(v) for k, v in raw.get("comparisons", {}).items()}
        except Exception: self.gap_analyses, self.import_plans, self.templates, self.comparisons = {}, {}, {}, {}
    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True); temp = self.path.with_suffix(".tmp"); temp.write_text(json.dumps(self.to_dict(), indent=2, default=str), encoding="utf-8"); temp.replace(self.path)
        except Exception: pass


_singleton = None; _lock = threading.Lock()
def get_refinement_registry():
    global _singleton
    if _singleton is None:
        with _lock:
            if _singleton is None: _singleton = RefinementRegistry()
    return _singleton
