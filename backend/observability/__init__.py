"""backend.observability — OTel-semantic observability for MarketOS cognition."""
from .tracing import tracer, Tracer
from .telemetry_router import TelemetryRouter, get_telemetry_router
from .exporters import prometheus_text, cognition_json, entropy_json, recent_traces_json, topology_json
from .entropy_metrics import measure_entropy
from .schemas.trace_span import TraceSpan, SpanStatus
from .schemas.replay_trace import ReplayTrace
from .schemas.cognition_snapshot import CognitionSnapshot
from .schemas.entropy_report import EntropyReport
from .schemas.topology_state import TopologyState

__all__ = [
    "tracer", "Tracer",
    "TelemetryRouter", "get_telemetry_router",
    "prometheus_text", "cognition_json", "entropy_json",
    "recent_traces_json", "topology_json",
    "measure_entropy",
    "TraceSpan", "SpanStatus",
    "ReplayTrace",
    "CognitionSnapshot",
    "EntropyReport",
    "TopologyState",
]
