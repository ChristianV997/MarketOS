"""backend.contracts.event_log — shared structural Protocol proving
backend.events.log and backend.orchestration.event_store.EventStore are
both append-only event logs with a compatible read/write surface, without
merging them into one file or changing either module's on-disk format or
existing call sites.

Why two logs exist and why this is additive-only, not a migration:
backend.events.log wraps backend.runtime.replay_store.RuntimeReplayStore
(a DuckDB-backed table, `EventEnvelope{event_id,type,ts,source,payload,
correlation_id,sequence_id}`) and backs ArtifactRegistry/ExperimentRegistry
lineage replay. backend.orchestration.event_store.EventStore is a JSONL
file (`{ts,workflow_id,workflow,step,event,data}`) and backs every dry-run/
shadow-mode gate + backend.experiments.audit_log's transition history.
These serve genuinely different purposes in this codebase today and
nothing currently cross-reads them — unifying the storage/schema was
explicitly flagged as out of scope; this module only proves both already
satisfy one common structural interface (append + tail), which is enough
for any future code that wants to treat "an event log" polymorphically
without caring which backend it is.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class EventLogProtocol(Protocol):
    """Structural interface both backend.events.log (a module, used as a
    namespace object) and backend.orchestration.event_store.EventStore
    (a class instance) already satisfy — checked via isinstance in
    tests/test_contracts/test_event_log_protocol.py, not enforced by
    inheritance. Deliberately minimal: only the two operations both
    backends already expose under the same name."""

    def append(self, *args: Any, **kwargs: Any) -> Any: ...

    def tail(self, *args: Any, **kwargs: Any) -> list: ...


__all__ = ["EventLogProtocol"]
