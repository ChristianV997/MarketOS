from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from .portfolio_actions import PortfolioActionSet
from .scenario import PortfolioOptimizationPlan


class OptimizationRegistry:
    def __init__(self, path=None):
        self.path = Path(path or os.getenv("MARKETOS_OPTIMIZATION_STATE", "state/portfolio_optimization_registry.json"))
        self.action_sets = {}; self.plans = {}; self.load()

    def register_action_set(self, item): self.action_sets[item.action_set_id] = item; self.save(); return item
    def get_action_set(self, item_id): return self.action_sets.get(item_id)
    def list_action_sets(self, workspace_id=None, limit=50): return sorted([x for x in self.action_sets.values() if workspace_id is None or x.workspace_id == workspace_id], key=lambda x: x.created_at, reverse=True)[:max(0, min(int(limit), 500))]
    def register_plan(self, item): self.plans[item.optimization_id] = item; self.save(); return item
    def get_plan(self, item_id): return self.plans.get(item_id)
    def list_plans(self, workspace_id=None, limit=50): return sorted([x for x in self.plans.values() if workspace_id is None or x.workspace_id == workspace_id], key=lambda x: x.created_at, reverse=True)[:max(0, min(int(limit), 500))]
    def latest_plan(self, workspace_id=None):
        items = self.list_plans(workspace_id, 1); return items[0] if items else None
    def clear_for_tests(self): self.action_sets.clear(); self.plans.clear(); self.save()
    def to_dict(self): return {"action_sets": {k: v.to_dict() for k, v in self.action_sets.items()}, "plans": {k: v.to_dict() for k, v in self.plans.items()}}
    def load(self):
        try:
            if not self.path.exists(): return
            raw = json.loads(self.path.read_text(encoding="utf-8")); self.action_sets = {k: PortfolioActionSet.from_dict(v) for k, v in raw.get("action_sets", {}).items()}; self.plans = {k: PortfolioOptimizationPlan.from_dict(v) for k, v in raw.get("plans", {}).items()}
        except Exception: self.action_sets, self.plans = {}, {}
    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True); temp = self.path.with_suffix(".tmp"); temp.write_text(json.dumps(self.to_dict(), indent=2, default=str), encoding="utf-8"); temp.replace(self.path)
        except Exception: pass


_singleton = None; _lock = threading.Lock()
def get_optimization_registry():
    global _singleton
    if _singleton is None:
        with _lock:
            if _singleton is None: _singleton = OptimizationRegistry()
    return _singleton
