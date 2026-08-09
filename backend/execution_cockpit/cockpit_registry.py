from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from .cockpit_models import CockpitAction, CockpitApproval, CockpitCheckpoint, CockpitExecution, CockpitRunSummary


class CockpitRegistry:
    def __init__(self, path=None):
        self.path = Path(path or os.getenv("MARKETOS_COCKPIT_STATE", "state/execution_cockpit_registry.json"))
        self.actions, self.approvals, self.executions, self.checkpoints, self.summaries = {}, {}, {}, {}, {}
        self.load()
    def to_dict(self): return {"actions": {k: v.to_dict() for k, v in self.actions.items()}, "approvals": {k: v.to_dict() for k, v in self.approvals.items()}, "executions": {k: v.to_dict() for k, v in self.executions.items()}, "checkpoints": {k: v.to_dict() for k, v in self.checkpoints.items()}, "summaries": {k: v.to_dict() for k, v in self.summaries.items()}}
    def load(self):
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8")); self.actions = {k: CockpitAction.from_dict(v) for k, v in raw.get("actions", {}).items()}; self.approvals = {k: CockpitApproval.from_dict(v) for k, v in raw.get("approvals", {}).items()}; self.executions = {k: CockpitExecution.from_dict(v) for k, v in raw.get("executions", {}).items()}; self.checkpoints = {k: CockpitCheckpoint.from_dict(v) for k, v in raw.get("checkpoints", {}).items()}; self.summaries = {k: CockpitRunSummary.from_dict(v) for k, v in raw.get("summaries", {}).items()}
        except Exception: pass
    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True); tmp = self.path.with_suffix(".tmp"); tmp.write_text(json.dumps(self.to_dict(), indent=2, default=str), encoding="utf-8"); tmp.replace(self.path)
        except Exception: pass
    def register_action(self, x): self.actions[x.action_id] = x; self.save(); return x
    update_action = register_action
    def get_action(self, x): return self.actions.get(x)
    def list_actions(self, workspace_id=None, status=None, action_type=None, source_task_id=None, limit=100): return sorted([x for x in self.actions.values() if (workspace_id is None or x.workspace_id == workspace_id) and (status is None or x.status == status) and (action_type is None or x.action_type == action_type) and (source_task_id is None or x.source_task_id == source_task_id)], key=lambda x: x.created_at, reverse=True)[:max(0, min(int(limit), 500))]
    def register_approval(self, x): self.approvals[x.approval_id] = x; self.save(); return x
    update_approval = register_approval
    def get_approval(self, x): return self.approvals.get(x)
    def list_approvals(self, workspace_id=None, action_id=None, decision=None, limit=100): return sorted([x for x in self.approvals.values() if (workspace_id is None or x.workspace_id == workspace_id) and (action_id is None or x.action_id == action_id) and (decision is None or x.decision == decision)], key=lambda x: x.created_at, reverse=True)[:max(0, min(int(limit), 500))]
    def register_execution(self, x): self.executions[x.execution_id] = x; self.save(); return x
    update_execution = register_execution
    def get_execution(self, x): return self.executions.get(x)
    def list_executions(self, workspace_id=None, action_id=None, source_task_id=None, status=None, limit=100): return sorted([x for x in self.executions.values() if (workspace_id is None or x.workspace_id == workspace_id) and (action_id is None or x.action_id == action_id) and (source_task_id is None or x.source_task_id == source_task_id) and (status is None or x.status == status)], key=lambda x: x.started_at or 0, reverse=True)[:max(0, min(int(limit), 500))]
    def register_checkpoint(self, x): self.checkpoints[x.checkpoint_id] = x; self.save(); return x
    def get_checkpoint(self, x): return self.checkpoints.get(x)
    def list_checkpoints(self, workspace_id=None, execution_id=None, action_id=None, limit=200): return sorted([x for x in self.checkpoints.values() if (workspace_id is None or x.workspace_id == workspace_id) and (execution_id is None or x.execution_id == execution_id) and (action_id is None or x.action_id == action_id)], key=lambda x: x.created_at)[:max(0, min(int(limit), 1000))]
    def register_summary(self, x): self.summaries[x.summary_id] = x; self.save(); return x
    def get_summary(self, x): return self.summaries.get(x)
    def list_summaries(self, workspace_id=None, plan_id=None, limit=100): return sorted([x for x in self.summaries.values() if (workspace_id is None or x.workspace_id == workspace_id) and (plan_id is None or x.plan_id == plan_id)], key=lambda x: x.created_at, reverse=True)[:max(0, min(int(limit), 500))]
    def latest_summary(self, workspace_id=None, plan_id=None): return next(iter(self.list_summaries(workspace_id, plan_id, 1)), None)
    def clear_for_tests(self): self.actions.clear(); self.approvals.clear(); self.executions.clear(); self.checkpoints.clear(); self.summaries.clear(); self.save()

_singleton = None; _lock = threading.Lock()
def get_cockpit_registry():
    global _singleton
    if _singleton is None:
        with _lock:
            if _singleton is None: _singleton = CockpitRegistry()
    return _singleton
