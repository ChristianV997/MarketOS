"""Local-only canonical event repository foundation; adapters make no network calls."""
from __future__ import annotations
import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Protocol, Sequence
from backend.contracts.events import Event

@dataclass(frozen=True)
class AppendResult:
    event_id: str; appended: bool; idempotent: bool = False

class EventRepository(Protocol):
    def append(self, event: Event) -> AppendResult: ...
    def append_many(self, events: Sequence[Event]) -> list[AppendResult]: ...
    def get(self, event_id: str) -> Event | None: ...
    def stream(self, event_type: str | None = None, aggregate_id: str | None = None, limit: int | None = None) -> Iterator[Event]: ...
    def replay(self, since: float | None = None, until: float | None = None, **filters) -> list[Event]: ...
    def tail(self, n: int = 100, event_type: str | None = None) -> list[Event]: ...

class InMemoryEventRepository:
    """Test/golden-fixture repository with idempotency by event id."""
    def __init__(self): self._events: list[Event]=[];self._by_id:dict[str,Event]={};self._lock=threading.Lock()
    def append(self,event:Event)->AppendResult:
        with self._lock:
            if event.event_id in self._by_id:return AppendResult(event.event_id,False,True)
            self._events.append(event);self._by_id[event.event_id]=event;return AppendResult(event.event_id,True)
    def append_many(self,events:Sequence[Event])->list[AppendResult]: return [self.append(event) for event in events]
    def get(self,event_id:str)->Event|None:return self._by_id.get(event_id)
    def stream(self,event_type=None,aggregate_id=None,limit=None)->Iterator[Event]:
        rows=[x for x in self._events if (event_type is None or x.event_type==event_type) and (aggregate_id is None or x.aggregate_id==aggregate_id)]
        yield from rows[:limit] if limit is not None else rows
    def replay(self,since=None,until=None,**filters)->list[Event]: return [x for x in self.stream(**filters) if (since is None or x.occurred_at>=since) and (until is None or x.occurred_at<=until)]
    def tail(self,n=100,event_type=None)->list[Event]: return list(self.stream(event_type=event_type))[-max(0,n):]

class JsonlEventRepository(InMemoryEventRepository):
    """Canonical JSONL adapter. Invalid/torn lines are skipped on load."""
    def __init__(self,path:str|Path):
        super().__init__();self.path=Path(path);self._load()
    def _load(self):
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try:InMemoryEventRepository.append(self, Event.from_dict(json.loads(line)))
                except Exception:continue
        except OSError:pass
    def append(self,event:Event)->AppendResult:
        result=super().append(event)
        if result.appended:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            with self.path.open("a",encoding="utf-8") as handle:handle.write(event.canonical_json()+"\n");handle.flush()
        return result
