"""TraceSpan — OTel-semantic trace span for cognitive operations."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any
from enum import Enum


class SpanStatus(str, Enum):
    OK      = "ok"
    ERROR   = "error"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


@dataclass
class TraceSpan:
    """An OpenTelemetry-compatible trace span for one cognitive operation.

    Follows OTel semantic conventions:
      - trace_id: identifies the full causal chain
      - span_id:  identifies this individual operation
      - parent_span_id: links to the parent operation
      - name: operation name (e.g. "sleep.consolidation", "lineage.track")
      - attributes: key-value pairs for filtering/search
    """
    span_id:       str
    trace_id:      str
    name:          str
    start_ts:      float  = field(default_factory=time.time)
    end_ts:        float  = 0.0
    status:        SpanStatus = SpanStatus.OK
    parent_span_id: str   = ""
    workspace:     str    = "default"
    source:        str    = ""
    attributes:    dict[str, Any] = field(default_factory=dict)
    events:        list[dict[str, Any]] = field(default_factory=list)
    error_message: str    = ""

    @classmethod
    def start(
        cls,
        name: str,
        trace_id: str = "",
        parent_span_id: str = "",
        workspace: str = "default",
        source: str = "",
        **attributes: Any,
    ) -> "TraceSpan":
        return cls(
            span_id=uuid.uuid4().hex[:16],
            trace_id=trace_id or uuid.uuid4().hex[:32],
            name=name,
            parent_span_id=parent_span_id,
            workspace=workspace,
            source=source,
            attributes=attributes,
        )

    def finish(self, status: SpanStatus = SpanStatus.OK, error: str = "") -> "TraceSpan":
        self.end_ts       = time.time()
        self.status       = status
        self.error_message = error
        return self

    def add_event(self, name: str, **attrs: Any) -> None:
        self.events.append({"name": name, "ts": time.time(), **attrs})

    @property
    def duration_ms(self) -> float:
        end = self.end_ts or time.time()
        return (end - self.start_ts) * 1000.0

    @property
    def ok(self) -> bool:
        return self.status == SpanStatus.OK

    def to_dict(self) -> dict[str, Any]:
        return {
            "span_id":        self.span_id,
            "trace_id":       self.trace_id,
            "name":           self.name,
            "start_ts":       self.start_ts,
            "end_ts":         self.end_ts,
            "duration_ms":    self.duration_ms,
            "status":         self.status.value,
            "parent_span_id": self.parent_span_id,
            "workspace":      self.workspace,
            "source":         self.source,
            "attributes":     self.attributes,
            "events":         self.events,
            "error_message":  self.error_message,
        }
