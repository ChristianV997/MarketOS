"""Tests for services.supplier_logistics_consulting_integration.controls."""
import pytest

from backend.workspaces.client_workspace import ClientWorkspace
from services.supplier_logistics_consulting_integration import controls
from services.supplier_logistics_research import controls as upstream_controls


class TestReExportsAreGenuineReuseNotReimplementation:
    @pytest.mark.parametrize("name", ["NegativeControlError", "is_verified", "reject_unsafe_input", "require_matching_currency", "require_present"])
    def test_symbol_is_the_same_object_as_upstream(self, name):
        assert getattr(controls, name) is getattr(upstream_controls, name)


class TestRequireWorkspaceMatch:
    def test_accepts_the_genuine_registered_workspace(self, workspace, ws_registry):
        result = controls.require_workspace_match(workspace.workspace_id, workspace, registry=ws_registry)
        assert result.workspace_id == workspace.workspace_id

    def test_rejects_a_different_workspace_object(self, workspace, other_workspace, ws_registry):
        with pytest.raises(controls.WorkspaceMismatchError):
            controls.require_workspace_match(workspace.workspace_id, other_workspace, registry=ws_registry)

    def test_rejects_a_forged_workspace_claiming_the_right_id(self, workspace, ws_registry):
        forged = ClientWorkspace(workspace_id=workspace.workspace_id, name="forged-name", workspace_type="client_service")
        with pytest.raises(controls.WorkspaceMismatchError):
            controls.require_workspace_match(workspace.workspace_id, forged, registry=ws_registry)

    def test_rejects_an_unregistered_workspace(self, ws_registry):
        unregistered = ClientWorkspace(name="never-registered", workspace_type="client_service")
        with pytest.raises(controls.WorkspaceMismatchError):
            controls.require_workspace_match(unregistered.workspace_id, unregistered, registry=ws_registry)

    def test_rejects_an_empty_claimed_workspace_id(self, workspace, ws_registry):
        with pytest.raises(controls.WorkspaceMismatchError):
            controls.require_workspace_match("", workspace, registry=ws_registry)


class TestRejectCrossClientLeakage:
    def test_passes_a_clean_payload(self):
        controls.reject_cross_client_leakage({"status": "ready_for_review", "blockers": []})  # must not raise

    def test_rejects_a_secret_shaped_key(self):
        with pytest.raises(controls.CrossClientLeakageError):
            controls.reject_cross_client_leakage({"api_key": "whatever-the-value-is"})

    def test_rejects_a_cross_client_value_marker(self):
        with pytest.raises(controls.CrossClientLeakageError):
            controls.reject_cross_client_leakage({"note": "same terms as our other_client engagement"})

    def test_rejects_an_internal_strategy_marker_not_covered_by_upstream_controls(self):
        # "pricing formula" trips TrustOS's own _FORBIDDEN_VALUE_MARKERS but
        # not services.supplier_logistics_research.controls' narrower
        # secret/html/cross-client patterns -- proving this is genuine
        # additional coverage, not a duplicate check.
        note = "our internal pricing formula for other suppliers"
        upstream_controls.reject_unsafe_input(note, field_name="test")  # passes upstream, as expected
        with pytest.raises(controls.CrossClientLeakageError):
            controls.reject_cross_client_leakage({"note": note})
