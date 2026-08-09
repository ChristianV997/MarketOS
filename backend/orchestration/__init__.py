"""backend.orchestration — multi-platform workflow coordination.

Modules:
  state_machine — per-platform health tracking + circuit breaker
  event_store   — append-only workflow execution log with crash recovery
  workflow      — Step/Workflow engine with dependency DAG + compensation
  rate_mesh     — cross-platform rate coordination (peer backoff on throttle)
  adapter       — PlatformAdapter wrapping existing integration clients
  transaction   — atomic cross-platform campaign launch with rollback

The framework is deliberately synchronous (thread-parallel where needed):
every existing integration client is sync, and the workflow engine must
compose with them without an async/sync seam.
"""
from backend.orchestration.state_machine import PlatformHealth, HealthState, health_registry
from backend.orchestration.event_store import EventStore, event_store
from backend.orchestration.workflow import Step, StepResult, Workflow, WorkflowResult
from backend.orchestration.rate_mesh import RateMesh, rate_mesh
from backend.orchestration.adapter import PlatformAdapter
from backend.orchestration.transaction import LaunchTransaction, TransactionResult

__all__ = [
    "PlatformHealth", "HealthState", "health_registry",
    "EventStore", "event_store",
    "Step", "StepResult", "Workflow", "WorkflowResult",
    "RateMesh", "rate_mesh",
    "PlatformAdapter",
    "LaunchTransaction", "TransactionResult",
]
