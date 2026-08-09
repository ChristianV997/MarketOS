"""backend.events — canonical event type constants for the MarketOS event bus.

All publishers (orchestrator, workers, API) and all consumers (WebSocket,
frontend) must use these constants as the ``type`` field in every event dict.
"""
from backend.events.schemas import (
    ORCHESTRATOR_TICK,
    SIGNALS_UPDATED,
    SIMULATION_COMPLETED,
    PLAYBOOK_UPDATED,
    CAMPAIGN_UPDATED,
    ANOMALY_DETECTED,
    WORKER_HEALTH,
    RUNTIME_SNAPSHOT,
    TASK_INVENTORY,
    DECISION_LOGGED,
)
from .repository import AppendResult, EventRepository, InMemoryEventRepository, JsonlEventRepository

__all__ = [
    "ORCHESTRATOR_TICK",
    "SIGNALS_UPDATED",
    "SIMULATION_COMPLETED",
    "PLAYBOOK_UPDATED",
    "CAMPAIGN_UPDATED",
    "ANOMALY_DETECTED",
    "WORKER_HEALTH",
    "RUNTIME_SNAPSHOT",
    "TASK_INVENTORY",
    "DECISION_LOGGED",
    "AppendResult",
    "EventRepository",
    "InMemoryEventRepository",
    "JsonlEventRepository",
]
