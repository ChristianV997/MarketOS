"""Read-normalizing adapters for legacy local stores; no caller migration."""
from __future__ import annotations
import json
from pathlib import Path
from backend.contracts.events import Event

class LegacyWorkflowEventStoreAdapter:
    read_only=True
    def __init__(self, store=None):
        self.store=store
    def stream(self,limit=100):
        if self.store is None:
            from backend.orchestration.event_store import event_store
            self.store=event_store
        rows=list(self.store._iter_events())[-max(0,limit):]
        return [Event.from_workflow_record(row) for row in rows]
    def get(self,event_id): return next((x for x in self.stream(10000) if x.event_id==event_id),None)
    def append(self,event): raise NotImplementedError("legacy workflow adapter is read-only; preserve existing EventStore semantics")

class LegacyRuntimeReplayAdapter:
    read_only=True
    def __init__(self, store=None): self.store=store
    def tail(self,n=100,event_type=None):
        if self.store is None:
            from backend.runtime.replay_store import get_replay_store
            self.store=get_replay_store()
        rows=self.store.tail(n,event_type=event_type)
        return [self._normalize(row) for row in rows]
    def stream(self,limit=100,event_type=None): return self.tail(limit,event_type)
    def _normalize(self,row):
        payload=row.get("payload",{})
        if isinstance(payload,str):
            try: payload=json.loads(payload)
            except Exception: payload={"legacy_payload":payload}
        return Event(str(row.get("event_id") or f"replay:{row.get('ts',0)}"),payload.pop("workspace_id",None) if isinstance(payload,dict) else None,"runtime",str(row.get("event_id") or "runtime"),str(row.get("type") or "legacy.runtime.event"),int(row.get("event_version",1) or 1),float(row.get("ts",0) or 0),correlation_id=row.get("correlation_id"),source=str(row.get("source") or "legacy.runtime_replay"),payload=payload if isinstance(payload,dict) else {"legacy_payload":payload},metadata={"legacy_sequence_id":row.get("sequence_id"),"legacy_replay":True})
    def append(self,event): raise NotImplementedError("legacy runtime adapter is read-only; preserve broker/replay-store ownership")
