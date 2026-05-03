"""ReplayTrace — a complete trace of one replay/consolidation execution."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .trace_span import TraceSpan


@dataclass
class ReplayTrace:
    """Full execution trace for one replay or consolidation cycle.

    Inspired by Temporal workflow history: every step is a span,
    spans are ordered, and the full trace is replayable from the
    span list alone.
    """
    trace_id:   str
    name:       str               # e.g. "sleep.cycle", "replay.hydration"
    workspace:  str = "default"
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    spans:      list[TraceSpan] = field(default_factory=list)
    root_span_id: str = ""
    ok:         bool  = True
    error:      str   = ""

    def add_span(self, span: TraceSpan) -> None:
        self.spans.append(span)

    def finish(self, ok: bool = True, error: str = "") -> None:
        self.finished_at = time.time()
        self.ok    = ok
        self.error = error

    @property
    def duration_ms(self) -> float:
        end = self.finished_at or time.time()
        return (end - self.started_at) * 1000.0

    @property
    def span_count(self) -> int:
        return len(self.spans)

    @property
    def error_spans(self) -> list[TraceSpan]:
        from .trace_span import SpanStatus
        return [s for s in self.spans if s.status != SpanStatus.OK]

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id":    self.trace_id,
            "name":        self.name,
            "workspace":   self.workspace,
            "started_at":  self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "span_count":  self.span_count,
            "ok":          self.ok,
            "error":       self.error,
            "spans":       [s.to_dict() for s in self.spans],
        }
