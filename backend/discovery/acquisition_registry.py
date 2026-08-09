from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from .acquisition_plan import EvidenceAcquisitionPlan
from .connector_stubs import EvidenceConnectorStub


class AcquisitionRegistry:
    def __init__(self, path=None):
        self.path = Path(path or os.getenv("MARKETOS_ACQUISITION_STATE", "state/acquisition_registry.json")); self.plans = {}; self.stubs = {}; self._lock = threading.RLock(); self.load()
    def register_plan(self, plan): self.plans[plan.plan_id] = plan; self.save(); return plan
    def get_plan(self, plan_id): return self.plans.get(plan_id)
    def list_plans(self, workspace_id=None, parser_type=None, status=None, limit=50): return list(reversed([x for x in self.plans.values() if (workspace_id is None or x.workspace_id == workspace_id) and (parser_type is None or x.parser_type == parser_type) and (status is None or x.status == status)]))[:max(0, min(int(limit), 500))]
    def update_plan(self, plan): return self.register_plan(plan)
    def register_stub(self, stub): self.stubs[stub.connector_name] = stub; self.save(); return stub
    def get_stub(self, name): return self.stubs.get(name)
    def list_stubs(self, limit=100): return list(self.stubs.values())[:max(0, min(int(limit), 500))]
    def clear_for_tests(self): self.plans.clear(); self.stubs.clear(); self.save()
    def to_dict(self): return {"plans": {k: v.to_dict() for k, v in self.plans.items()}, "stubs": {k: v.to_dict() for k, v in self.stubs.items()}}
    def load(self):
        try:
            if not self.path.exists(): return
            raw = json.loads(self.path.read_text(encoding="utf-8")); self.plans = {k: EvidenceAcquisitionPlan.from_dict(v) for k, v in raw.get("plans", {}).items()}; self.stubs = {k: EvidenceConnectorStub.from_dict(v) for k, v in raw.get("stubs", {}).items()}
        except Exception: self.plans, self.stubs = {}, {}
    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True); temp = self.path.with_suffix(".tmp"); temp.write_text(json.dumps(self.to_dict(), indent=2, default=str), encoding="utf-8"); temp.replace(self.path)
        except Exception: pass


_singleton = None; _lock = threading.Lock()
def get_acquisition_registry():
    global _singleton
    if _singleton is None:
        with _lock:
            if _singleton is None: _singleton = AcquisitionRegistry()
    return _singleton
