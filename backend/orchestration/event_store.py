"""backend.orchestration.event_store — append-only workflow execution log.

Every workflow step emits an event to ``state/workflow_executions.jsonl``:

    {"ts": ..., "workflow_id": ..., "workflow": ..., "step": ...,
     "event": "workflow_started|step_started|step_completed|step_failed|
               step_compensated|workflow_completed|workflow_failed",
     "data": {...}}

Invariant the rest of the system relies on: *a workflow_started event with
no matching workflow_completed/workflow_failed means the process died
mid-workflow* — ``incomplete_workflows()`` surfaces exactly those on
startup so callers can compensate or resume.

The log also powers prediction→outcome pairing: a launch step records
``predicted_roas`` in its data; ``find_launch_event(campaign_id)`` recovers
it later when real ROAS arrives, even across restarts.

Writes are line-buffered appends under a lock — crash-safe in the sense
that a torn final line is skipped on read, never corrupting earlier events.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from typing import Any, Iterator

_log = logging.getLogger(__name__)

_DEFAULT_PATH = os.path.join(
    os.getenv("STATE_DIR", "state"), "workflow_executions.jsonl")

_TERMINAL = {"workflow_completed", "workflow_failed"}


def new_workflow_id(prefix: str = "wf") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class EventStore:
    def __init__(self, path: str | None = None):
        self.path = path or _DEFAULT_PATH
        self._lock = threading.Lock()

    # ── writes ───────────────────────────────────────────────────────────

    def append(self, workflow_id: str, event: str, *, workflow: str = "",
               step: str = "", data: dict[str, Any] | None = None) -> dict:
        record = {
            "ts": time.time(),
            "workflow_id": workflow_id,
            "workflow": workflow,
            "step": step,
            "event": event,
            "data": data or {},
        }
        line = json.dumps(record, default=str)
        with self._lock:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(self.path, "a") as fh:
                fh.write(line + "\n")
        return record

    # ── reads ────────────────────────────────────────────────────────────

    def _iter_events(self) -> Iterator[dict]:
        if not os.path.exists(self.path):
            return
        with open(self.path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    # torn tail line from a crash mid-write — ignore
                    continue

    def events_for(self, workflow_id: str) -> list[dict]:
        return [e for e in self._iter_events()
                if e.get("workflow_id") == workflow_id]

    def incomplete_workflows(self) -> list[dict]:
        """Workflows that started but never reached a terminal event.

        Returns [{workflow_id, workflow, started_at, last_event,
                  completed_steps}] — enough for a caller to decide whether
        to compensate, resume, or ignore.
        """
        started: dict[str, dict] = {}
        finished: set[str] = set()
        completed_steps: dict[str, list[str]] = {}
        last_event: dict[str, str] = {}

        for e in self._iter_events():
            wid = e.get("workflow_id", "")
            ev = e.get("event", "")
            last_event[wid] = ev
            if ev == "workflow_started":
                started[wid] = e
            elif ev in _TERMINAL:
                finished.add(wid)
            elif ev == "step_completed":
                completed_steps.setdefault(wid, []).append(e.get("step", ""))

        return [
            {
                "workflow_id": wid,
                "workflow": e.get("workflow", ""),
                "started_at": e.get("ts"),
                "last_event": last_event.get(wid, ""),
                "completed_steps": completed_steps.get(wid, []),
            }
            for wid, e in started.items() if wid not in finished
        ]

    def find_launch_event(self, campaign_id: str) -> dict | None:
        """Locate the step_completed event whose output created campaign_id.

        Used to pair a launch-time ROAS prediction with the realized ROAS
        for the calibration loop, surviving restarts.
        """
        for e in self._iter_events():
            if e.get("event") != "step_completed":
                continue
            data = e.get("data") or {}
            out = data.get("output") or {}
            if out.get("campaign_id") == campaign_id or \
                    campaign_id in (out.get("campaign_ids") or []):
                return e
        return None

    def tail(self, n: int = 50) -> list[dict]:
        events = list(self._iter_events())
        return events[-n:]


event_store = EventStore()

__all__ = ["EventStore", "event_store", "new_workflow_id"]
