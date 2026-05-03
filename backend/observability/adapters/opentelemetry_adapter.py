"""opentelemetry_adapter — bridge between internal tracer and OTel SDK."""
from __future__ import annotations

import time
from typing import Any

from ..schemas.trace_span import TraceSpan, SpanStatus


class OTelAdapter:
    """Exports internal TraceSpan objects to an OTel-compatible backend."""

    def __init__(self, endpoint: str = "", service_name: str = "marketos") -> None:
        self.endpoint = endpoint
        self.service_name = service_name
        self._spans_exported = 0

    def export_span(self, span: TraceSpan) -> bool:
        """Export a single span. Returns True on success."""
        try:
            payload = self._to_otel_span(span)
            self._emit(payload)
            self._spans_exported += 1
            return True
        except Exception:
            return False

    def export_batch(self, spans: list[TraceSpan]) -> int:
        """Export multiple spans. Returns count successfully exported."""
        return sum(1 for s in spans if self.export_span(s))

    def _to_otel_span(self, span: TraceSpan) -> dict[str, Any]:
        return {
            "traceId": span.trace_id,
            "spanId": span.span_id,
            "parentSpanId": span.parent_span_id or None,
            "name": span.name,
            "kind": 1,  # SPAN_KIND_INTERNAL
            "startTimeUnixNano": int(span.start_ts * 1e9),
            "endTimeUnixNano": int((span.end_ts or time.time()) * 1e9),
            "status": {"code": 1 if span.status == SpanStatus.OK else 2},
            "attributes": {
                "workspace": span.workspace,
                "source": span.source,
                "error": span.error_message or "",
            },
            "events": [
                {
                    "name": e.get("name", ""),
                    "timeUnixNano": int(e.get("ts", time.time()) * 1e9),
                    "attributes": {k: v for k, v in e.items() if k not in ("name", "ts")},
                }
                for e in span.events
            ],
        }

    def _emit(self, payload: dict[str, Any]) -> None:
        if not self.endpoint:
            return
        try:
            import urllib.request
            import json
            body = json.dumps({"resourceSpans": [{"scopeSpans": [{"spans": [payload]}]}]}).encode()
            req = urllib.request.Request(
                self.endpoint,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=2):
                pass
        except Exception:
            pass

    @property
    def spans_exported(self) -> int:
        return self._spans_exported


_adapter: OTelAdapter | None = None


def get_otel_adapter() -> OTelAdapter:
    global _adapter
    if _adapter is None:
        import os
        _adapter = OTelAdapter(
            endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", ""),
            service_name=os.getenv("OTEL_SERVICE_NAME", "marketos"),
        )
    return _adapter
