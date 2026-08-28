"""Boundary tests for backend/workspaces/**.

Scope: workspace identity, cross-workspace isolation, path-traversal
rejection in the artifact store, dry-run/human-approval defaults, and
absence of provider/network/payment/order/customer-message authority in
this package. Does not duplicate tests/test_workspaces/test_artifact_
store.py, tests/test_workspaces/test_live_mode_checklist.py, tests/
test_client_workspace_isolation.py, or tests/test_resource_execution_
governor.py, all of which already exist and cover their own modules in
depth; this file targets the identity/isolation/traversal boundary
specifically, plus one focused defect this pass found and repaired in
the canonical owner (ArtifactStore).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

import backend.core.persistence as persistence
from backend.workspaces.artifact_store import ArtifactStore
from backend.workspaces.client_workspace import ClientWorkspace
from backend.workspaces.registry import WorkspaceRegistry

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch, tmp_path):
    monkeypatch.setattr(persistence, "STATE_DIR", str(tmp_path))
    return tmp_path


# --- Workspace identity isolation --------------------------------------------

def test_workspace_identity_is_deterministic_for_the_same_name():
    a = ClientWorkspace(name="acme-co")
    b = ClientWorkspace(name="acme-co")
    assert a.workspace_id == b.workspace_id
    assert a.workspace_id  # non-empty


def test_workspace_identity_differs_for_different_names():
    a = ClientWorkspace(name="acme-co")
    b = ClientWorkspace(name="beta-co")
    assert a.workspace_id != b.workspace_id


def test_workspace_identity_is_not_reused_across_explicit_ids():
    explicit = ClientWorkspace(workspace_id="custom-id", name="acme-co")
    assert explicit.workspace_id == "custom-id"


# --- Cross-workspace read rejection ------------------------------------------

def test_registry_get_returns_none_for_an_unregistered_workspace_id():
    registry = WorkspaceRegistry()
    registry.register(ClientWorkspace(name="acme-co"))
    assert registry.get("some-other-workspace-id") is None


def test_registry_get_never_returns_a_different_workspaces_record():
    registry = WorkspaceRegistry()
    a = registry.register(ClientWorkspace(name="acme-co", owner_label="Acme"))
    b = registry.register(ClientWorkspace(name="beta-co", owner_label="Beta"))
    fetched_a = registry.get(a.workspace_id)
    fetched_b = registry.get(b.workspace_id)
    assert fetched_a.owner_label == "Acme"
    assert fetched_b.owner_label == "Beta"
    assert fetched_a.workspace_id != fetched_b.workspace_id


def test_artifact_store_reads_do_not_cross_workspace_boundaries():
    store = ArtifactStore()
    store.save("workspace-a", "exp-1", "result.json", {"secret": "a-only"})
    store.save("workspace-b", "exp-1", "result.json", {"secret": "b-only"})
    assert store.load("workspace-a", "exp-1", "result.json")["secret"] == "a-only"
    assert store.load("workspace-b", "exp-1", "result.json")["secret"] == "b-only"
    assert store.list_experiments("workspace-a") == store.list_experiments("workspace-b") == ["exp-1"]


# --- Path traversal rejection / workspace boundary leakage -------------------
#
# Regression coverage for a real defect this pass found and fixed in the
# canonical owner (backend/workspaces/artifact_store.py): path_for() built
# a path via os.path.join(workspace_id, ...) with no validation, so a
# traversal-shaped workspace_id/experiment_id/filename could escape the
# per-workspace sandbox entirely. Reproduced live before the fix (a crafted
# workspace_id wrote a file under an arbitrary absolute path outside
# STATE_DIR); confirmed closed by these tests after the fix.

@pytest.mark.parametrize("workspace_id", ["../escape", "../../etc/evil", "a/../../b"])
def test_artifact_store_rejects_workspace_id_path_traversal(workspace_id):
    store = ArtifactStore()
    with pytest.raises(ValueError):
        store.save(workspace_id, "exp-1", "result.json", {"leaked": True})


def test_artifact_store_rejects_experiment_id_path_traversal():
    store = ArtifactStore()
    with pytest.raises(ValueError):
        store.save("workspace-a", "../../escape", "result.json", {"leaked": True})


def test_artifact_store_rejects_filename_path_traversal():
    store = ArtifactStore()
    with pytest.raises(ValueError):
        store.save("workspace-a", "exp-1", "../../../escape.json", {"leaked": True})


def test_artifact_store_rejects_absolute_path_filename():
    store = ArtifactStore()
    with pytest.raises(ValueError):
        store.save("workspace-a", "exp-1", "/etc/passwd", {"leaked": True})


def test_artifact_store_list_experiments_fails_closed_to_empty_on_traversal():
    """list_experiments() keeps its existing never-raises contract: a
    rejected traversal attempt must resolve to [], not propagate."""
    store = ArtifactStore()
    assert store.list_experiments("../../../../tmp") == []


def test_artifact_store_load_rejects_traversal_rather_than_reading_outside_state(tmp_path):
    outside = tmp_path.parent / "outside-secret.json"
    outside.write_text('{"secret": true}', encoding="utf-8")
    store = ArtifactStore()
    with pytest.raises(ValueError):
        store.load("../..", "exp-1", outside.name)


def test_artifact_store_resolved_paths_always_stay_within_state_dir(tmp_path):
    store = ArtifactStore()
    path = store.path_for("workspace-a", "exp-1", "result.json")
    assert str(Path(path).resolve()).startswith(str(tmp_path.resolve()))


# --- Dry-run and human-approval defaults -------------------------------------

def test_client_workspace_defaults_are_dry_run_and_not_live():
    workspace = ClientWorkspace(name="new-client")
    assert workspace.dry_run_default is True
    assert workspace.live_mode_enabled is False


# --- Absence of provider, network, payment, order, and customer-message -----
# authority in this package's own modules (evaluation/trustos/
# client_workspace_isolation.py and evaluation/companyos/
# resource_execution_governor.py already enforce and test their own,
# broader safety invariants in dedicated test files; these two assertions
# are a light cross-check, not a re-test of that coverage).

def test_trustos_client_workspace_safety_summary_stays_read_only():
    from evaluation.trustos.client_workspace_isolation import ClientWorkspaceSafetySummary
    assert ClientWorkspaceSafetySummary().read_only is True
    with pytest.raises(ValueError):
        ClientWorkspaceSafetySummary(network_calls=True)


def test_companyos_resource_governor_decisions_stay_simulated_only():
    from evaluation.companyos.resource_execution_governor import ExecutionDecisionResult
    with pytest.raises(ValueError):
        ExecutionDecisionResult(
            request_id="req-1", action_type="launch_ad_experiment", outcome="allow",
            reason="test", blockers=(), warnings=(), approvals=(),
            budget_checks=(), quota_checks=(), priority_score=None, risk_score=None,
            dependencies=(), learning_requirement=None, next_best_action="test",
            simulated_only=False,
        )


_FORBIDDEN_MODULE_PREFIXES = (
    "requests", "httpx", "aiohttp", "urllib3", "socket",
    "backend.integrations", "backend.commerce.checkout", "backend.commerce.orders", "backend.commerce.fulfillment",
)


def test_workspace_modules_have_no_direct_provider_or_commerce_imports():
    """AST scan restricted to this package: workspace identity, artifact
    storage, and the registry must not themselves import a network client
    or a real-mutation commerce/integration module."""
    offenders = []
    for filename in ("client_workspace.py", "artifact_store.py", "registry.py"):
        path = ROOT / "backend" / "workspaces" / filename
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                if any(name == prefix or name.startswith(prefix + ".") for prefix in _FORBIDDEN_MODULE_PREFIXES):
                    offenders.append(f"{filename} imports {name}")
    assert not offenders, "\n".join(offenders)
