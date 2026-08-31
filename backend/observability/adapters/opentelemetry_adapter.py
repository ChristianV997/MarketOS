"""opentelemetry_adapter — bridge between internal tracer and OTel SDK."""
from __future__ import annotations

import enum
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from ..schemas.trace_span import TraceSpan, SpanStatus

log = logging.getLogger(__name__)

class OTELBoundaryState(enum.Enum):
    DISABLED = "disabled"
    CONFIGURED_BUT_BLOCKED = "configured_but_blocked"
    DRY_RUN = "dry_run"
    APPROVAL_REQUIRED = "approval_required"
    LIVE_NOT_IMPLEMENTED = "live_not_implemented"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"

@dataclass
class LangfuseOTELConfig:
    state: OTELBoundaryState = OTELBoundaryState.DISABLED
    endpoint_placeholder: str = "https://cloud.langfuse.com/api/public/otel"
    region: str = "us"
    credential_reference_id: str | None = None
    export_enabled: bool = False
    timeout_ms: int = 2000
    retry_cap: int = 3
    max_batch_size: int = 100
    max_payload_bytes: int = 65_536
    redaction_policy: str = "strict_drop_all_secrets_and_prompts"
    approval_requirement: str = "explicit_offline_ledger_approval_required"
    budget_usage_metadata: dict[str, Any] = field(default_factory=dict)


# Value-shape redaction: sensitive_keys (below) catches secret-named fields;
# this catches secret-*shaped* values under an innocuous key (e.g. a token
# accidentally logged under "note" or embedded in an error message).
_SECRET_SHAPED_VALUE = re.compile(
    r"(?is)("
    r"-----begin (?:rsa |ec |dsa |openssh )?private key-----"
    r"|ghp_[A-Za-z0-9_]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|sk-(?:live|test)?-?[A-Za-z0-9]{16,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|bearer [A-Za-z0-9._-]{10,}"
    r")"
)

class OTelAdapter:
    """Exports internal TraceSpan objects to an OTel-compatible backend."""

    def __init__(self, endpoint: str = "", service_name: str = "marketos", config: LangfuseOTELConfig | None = None) -> None:
        self.endpoint = endpoint
        self.service_name = service_name
        self.config = config or LangfuseOTELConfig()
        self._spans_exported = 0

    def export_span(self, span: TraceSpan) -> bool:
        """Export a single span. Returns True on success."""
        try:
            if self.config.state in (OTELBoundaryState.DISABLED, OTELBoundaryState.FAILED, OTELBoundaryState.UNAVAILABLE):
                return False

            if not self.config.credential_reference_id:
                self.config.state = OTELBoundaryState.CONFIGURED_BUT_BLOCKED
                return False

            if self.config.state == OTELBoundaryState.APPROVAL_REQUIRED:
                return False

            payload = self._to_otel_span(span)
            payload = self._redact(payload)

            # Bounded payload size: an oversized span is dropped, never
            # partially exported or exported unbounded.
            payload_bytes = len(json.dumps(payload, default=str).encode("utf-8", errors="replace"))
            if payload_bytes > self.config.max_payload_bytes:
                log.info("OTEL span export dropped: payload exceeded max_payload_bytes.")
                return False

            # Fail closed for live export
            if self.config.export_enabled or self.config.state == OTELBoundaryState.LIVE_NOT_IMPLEMENTED:
                # Live export not implemented, fail closed and do not call the network
                self.config.state = OTELBoundaryState.LIVE_NOT_IMPLEMENTED
                log.info("OTEL live export is blocked by boundary fail-closed policy.")
                return False

            if self.config.state == OTELBoundaryState.DRY_RUN:
                self._spans_exported += 1
                return True

            return False
        except Exception:
            return False

    def export_batch(self, spans: list[TraceSpan]) -> int:
        """Export multiple spans. Returns count successfully exported.

        Bounded by config.max_batch_size: spans beyond the cap are dropped
        (never attempted, never silently exported unbounded) and logged."""
        bounded = spans[: self.config.max_batch_size]
        if len(spans) > self.config.max_batch_size:
            log.info(
                "OTEL batch export capped: %d span(s) dropped beyond max_batch_size=%d.",
                len(spans) - self.config.max_batch_size, self.config.max_batch_size,
            )
        return sum(1 for s in bounded if self.export_span(s))

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

    def _redact(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Redact sensitive fields from the payload.

        Two independent checks, either one triggers redaction:
        - the *key name* looks sensitive (e.g. "api_key", "token"), or
        - the *value* itself is shaped like a real secret (PEM key, GitHub
          token, generic API-key prefix, bearer token) regardless of what
          key it is stored under -- catches a token accidentally logged
          under an innocuous key (e.g. an error message embedding one)."""
        sensitive_keys = {
            "api_key", "secret_key", "bearer_token", "cookie",
            "prompt", "raw_prompt", "model_output", "raw_model_output",
            "client_id", "email", "personal_data", "password", "token"
        }

        def _value_is_secret_shaped(value: Any) -> bool:
            return isinstance(value, str) and bool(_SECRET_SHAPED_VALUE.search(value))

        def _recursive_redact(obj: Any) -> Any:
            if isinstance(obj, dict):
                redacted_dict = {}
                for k, v in obj.items():
                    if any(sensitive in k.lower() for sensitive in sensitive_keys) or _value_is_secret_shaped(v):
                        redacted_dict[k] = "[REDACTED]"
                    else:
                        redacted_dict[k] = _recursive_redact(v)
                return redacted_dict
            elif isinstance(obj, list):
                return ["[REDACTED]" if _value_is_secret_shaped(item) else _recursive_redact(item) for item in obj]
            return obj

        return _recursive_redact(payload)

    def _emit(self, payload: dict[str, Any]) -> None:
        # We ensure _emit is never called in this boundary implementation.
        pass

    @property
    def spans_exported(self) -> int:
        return self._spans_exported


_adapter: OTelAdapter | None = None


def get_otel_adapter() -> OTelAdapter:
    global _adapter
    if _adapter is None:
        import os
        config = LangfuseOTELConfig()
        _adapter = OTelAdapter(
            endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", ""),
            service_name=os.getenv("OTEL_SERVICE_NAME", "marketos"),
            config=config
        )
    return _adapter
