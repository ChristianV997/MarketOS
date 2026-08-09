from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from .calendar_artifacts import OperatingCalendar
from .review_cadence import ProgressSnapshot, ReviewCadence
from .task_models import OperatingPlan, OperatingTask, TaskPacket


class OperationsRegistry:
    def __init__(self, path=None):
        self.path = Path(path or os.getenv("MARKETOS_OPERATIONS_STATE", "state/operations_registry.json"))
        self.plans = {}; self.tasks = {}; self.packets = {}; self.calendars = {}; self.cadences = {}; self.progress_snapshots = {}; self.load()
    def to_dict(self): return {"plans": {k: v.to_dict() for k, v in self.plans.items()}, "tasks": {k: v.to_dict() for k, v in self.tasks.items()}, "packets": {k: v.to_dict() for k, v in self.packets.items()}, "calendars": {k: v.to_dict() for k, v in self.calendars.items()}, "cadences": {k: v.to_dict() for k, v in self.cadences.items()}, "progress_snapshots": {k: v.to_dict() for k, v in self.progress_snapshots.items()}}
    def load(self):
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8")); self.plans = {k: OperatingPlan.from_dict(v) for k, v in raw.get("plans", {}).items()}; self.tasks = {k: OperatingTask.from_dict(v) for k, v in raw.get("tasks", {}).items()}; self.packets = {k: TaskPacket.from_dict(v) for k, v in raw.get("packets", {}).items()}; self.calendars = {k: OperatingCalendar.from_dict(v) for k, v in raw.get("calendars", {}).items()}; self.cadences = {k: ReviewCadence.from_dict(v) for k, v in raw.get("cadences", {}).items()}; self.progress_snapshots = {k: ProgressSnapshot.from_dict(v) for k, v in raw.get("progress_snapshots", {}).items()}
        except Exception: pass
    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True); tmp = self.path.with_suffix(".tmp"); tmp.write_text(json.dumps(self.to_dict(), indent=2, default=str), encoding="utf-8"); tmp.replace(self.path)
        except Exception: pass
    def register_plan(self, x): self.plans[x.plan_id] = x; self.save(); return x
    def get_plan(self, x): return self.plans.get(x)
    def list_plans(self, workspace_id=None, horizon=None, status=None, limit=50): return sorted([x for x in self.plans.values() if (workspace_id is None or x.workspace_id == workspace_id) and (horizon is None or x.horizon == horizon) and (status is None or x.status == status)], key=lambda x: x.created_at, reverse=True)[:max(0, min(int(limit), 500))]
    update_plan = register_plan
    def register_task(self, x): self.tasks[x.task_id] = x; self.save(); return x
    def get_task(self, x): return self.tasks.get(x)
    def list_tasks(self, workspace_id=None, plan_id=None, status=None, task_type=None, limit=200): return sorted([x for x in self.tasks.values() if (workspace_id is None or x.workspace_id == workspace_id) and (plan_id is None or x.metadata.get("plan_id") == plan_id) and (status is None or x.status == status) and (task_type is None or x.task_type == task_type)], key=lambda x: x.sequence_order)[:max(0, min(int(limit), 1000))]
    update_task = register_task
    def register_task_packet(self, x): self.packets[x.packet_id] = x; self.save(); return x
    def get_task_packet(self, x): return self.packets.get(x)
    def list_task_packets(self, workspace_id=None, plan_id=None, limit=200): return sorted([x for x in self.packets.values() if (workspace_id is None or x.workspace_id == workspace_id) and (plan_id is None or x.plan_id == plan_id)], key=lambda x: x.created_at, reverse=True)[:max(0, min(int(limit), 1000))]
    def register_calendar(self, x): self.calendars[x.calendar_id] = x; self.save(); return x
    def get_calendar(self, x): return self.calendars.get(x)
    def list_calendars(self, workspace_id=None, plan_id=None, limit=50): return sorted([x for x in self.calendars.values() if (workspace_id is None or x.workspace_id == workspace_id) and (plan_id is None or x.plan_id == plan_id)], key=lambda x: x.created_at, reverse=True)[:max(0, min(int(limit), 500))]
    def register_review_cadence(self, x): self.cadences[x.cadence_id] = x; self.save(); return x
    def get_review_cadence(self, x): return self.cadences.get(x)
    def list_review_cadences(self, workspace_id=None, plan_id=None, limit=50): return sorted([x for x in self.cadences.values() if (workspace_id is None or x.workspace_id == workspace_id) and (plan_id is None or x.plan_id == plan_id)], key=lambda x: x.created_at, reverse=True)[:max(0, min(int(limit), 500))]
    def register_progress_snapshot(self, x): self.progress_snapshots[x.snapshot_id] = x; self.save(); return x
    def get_progress_snapshot(self, x): return self.progress_snapshots.get(x)
    def list_progress_snapshots(self, workspace_id=None, plan_id=None, limit=100): return sorted([x for x in self.progress_snapshots.values() if (workspace_id is None or x.workspace_id == workspace_id) and (plan_id is None or x.plan_id == plan_id)], key=lambda x: x.created_at, reverse=True)[:max(0, min(int(limit), 500))]
    def latest_plan(self, workspace_id=None, horizon=None): return next(iter(self.list_plans(workspace_id, horizon, limit=1)), None)
    def clear_for_tests(self): self.plans.clear(); self.tasks.clear(); self.packets.clear(); self.calendars.clear(); self.cadences.clear(); self.progress_snapshots.clear(); self.save()

_singleton = None; _lock = threading.Lock()
def get_operations_registry():
    global _singleton
    if _singleton is None:
        with _lock:
            if _singleton is None: _singleton = OperationsRegistry()
    return _singleton
