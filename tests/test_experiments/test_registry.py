"""Tests for backend.experiments.registry.ExperimentRegistry — proves it's a
thin view over the existing ArtifactRegistry, not a duplicate store."""
import time

from backend.contracts.registry import ArtifactRegistry
from backend.experiments.envelope import CommercialRunEnvelope
from backend.experiments.registry import ExperimentRegistry


def _fresh_registry():
    # A brand-new ArtifactRegistry (not the process-wide singleton) so tests
    # don't leak state into each other via get_registry()'s global.
    return ExperimentRegistry(artifact_registry=ArtifactRegistry(), hydrate=False)


def test_register_is_visible_via_underlying_artifact_registry():
    artifact_registry = ArtifactRegistry()
    exp_registry = ExperimentRegistry(artifact_registry=artifact_registry, hydrate=False)
    env = CommercialRunEnvelope(service_name="product_research", workspace_id="ws-1")

    exp_registry.register(env)

    from_underlying = artifact_registry.by_type("commercial_run_envelope")
    assert len(from_underlying) == 1
    assert from_underlying[0].experiment_id == env.experiment_id


def test_get_returns_none_for_non_envelope_artifact_types():
    artifact_registry = ArtifactRegistry()
    exp_registry = ExperimentRegistry(artifact_registry=artifact_registry, hydrate=False)
    assert exp_registry.get("nonexistent") is None


def test_for_workspace_filters_by_workspace_id():
    reg = _fresh_registry()
    a = CommercialRunEnvelope(service_name="x", workspace_id="ws-a")
    b = CommercialRunEnvelope(service_name="x", workspace_id="ws-b")
    reg.register(a)
    reg.register(b)

    assert [e.experiment_id for e in reg.for_workspace("ws-a")] == [a.experiment_id]
    assert [e.experiment_id for e in reg.for_workspace("ws-b")] == [b.experiment_id]


def test_spend_this_month_sums_only_matching_workspace_this_month():
    reg = _fresh_registry()
    a = CommercialRunEnvelope(service_name="x", workspace_id="ws-a", actual_spend=30.0)
    b = CommercialRunEnvelope(service_name="x", workspace_id="ws-a", actual_spend=20.0)
    other_ws = CommercialRunEnvelope(service_name="x", workspace_id="ws-b", actual_spend=1000.0)
    reg.register(a)
    reg.register(b)
    reg.register(other_ws)

    assert reg.spend_this_month("ws-a") == 50.0


def test_spend_this_month_excludes_spend_from_before_this_month():
    reg = _fresh_registry()
    old = CommercialRunEnvelope(service_name="x", workspace_id="ws-a", actual_spend=999.0)
    old.created_at = time.time() - 90 * 24 * 3600  # ~3 months ago
    reg.register(old)

    assert reg.spend_this_month("ws-a") == 0.0
