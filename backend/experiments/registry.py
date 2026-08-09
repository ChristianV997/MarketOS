"""backend.experiments.registry — ExperimentRegistry, a thin domain-specific
view over the existing ArtifactRegistry (backend/contracts/registry.py).

Deliberately NOT a second store: register() delegates straight to
get_registry().register(), and all reads filter get_registry().by_type(
"commercial_run_envelope"). On first construction it best-effort hydrates
the shared ArtifactRegistry from the durable replay log so spend_this_month
gives correct cross-process-invocation totals (each CLI run is a fresh
process with an empty in-memory registry otherwise) — never raises, matches
the fail-silent persistence idiom used throughout this codebase.
"""
from __future__ import annotations

import threading

from backend.contracts.registry import ArtifactRegistry, get_registry

from .envelope import ARTIFACT_TYPE, CommercialRunEnvelope


class ExperimentRegistry:
    def __init__(self, artifact_registry: ArtifactRegistry | None = None, *, hydrate: bool = True) -> None:
        self._registry = artifact_registry or get_registry()
        if hydrate:
            try:
                self._registry.hydrate_from_replay()
            except Exception:
                pass

    def register(self, envelope: CommercialRunEnvelope) -> CommercialRunEnvelope:
        self._registry.register(envelope)
        return envelope

    def get(self, experiment_id: str) -> CommercialRunEnvelope | None:
        artifact = self._registry.get(experiment_id)
        return artifact if isinstance(artifact, CommercialRunEnvelope) else None

    def for_workspace(self, workspace_id: str) -> list[CommercialRunEnvelope]:
        return [
            e for e in self._registry.by_type(ARTIFACT_TYPE)
            if isinstance(e, CommercialRunEnvelope) and e.workspace_id == workspace_id
        ]

    def spend_this_month(self, workspace_id: str, *, now: float | None = None) -> float:
        import time as _time
        now = now if now is not None else _time.time()
        import datetime
        month_start = datetime.datetime.fromtimestamp(now, tz=datetime.timezone.utc).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        ).timestamp()
        return round(sum(
            e.actual_spend for e in self.for_workspace(workspace_id)
            if e.created_at >= month_start
        ), 2)


_experiment_registry: ExperimentRegistry | None = None
_lock = threading.Lock()


def get_experiment_registry() -> ExperimentRegistry:
    global _experiment_registry
    if _experiment_registry is None:
        with _lock:
            if _experiment_registry is None:
                _experiment_registry = ExperimentRegistry()
    return _experiment_registry
