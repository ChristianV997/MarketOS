"""Tests for services.status.commercial_status."""
from backend.workspaces.client_workspace import ClientWorkspace
from services.status import STATUSES, commercial_status


def test_seven_statuses_defined():
    assert len(STATUSES) == 7
    assert set(STATUSES) == {
        "ready_for_dry_run", "ready_for_internal_use", "ready_for_client_service",
        "needs_live_data", "needs_credentials", "future_saas", "future_dao",
    }


def test_no_requirements_is_ready_for_client_service():
    assert commercial_status() == "ready_for_client_service"


def test_requires_live_data_true_overrides_ready():
    assert commercial_status(requires_live_data=True) == "needs_live_data"


def test_missing_credential_reports_needs_credentials(monkeypatch):
    monkeypatch.setattr("backend.config.list_configured_services", lambda: {})
    ws = ClientWorkspace(name="x")
    assert commercial_status(requires_credentials=["shopify"], workspace=ws) == "needs_credentials"


def test_configured_credential_does_not_block(monkeypatch):
    monkeypatch.setattr("backend.config.list_configured_services", lambda: {"shopify": True})
    ws = ClientWorkspace(name="x")
    assert commercial_status(requires_credentials=["shopify"], workspace=ws) == "ready_for_client_service"


def test_no_workspace_supplied_skips_credential_check():
    # requires_credentials without a workspace can't be checked -> falls
    # through to the live-data/ready branch rather than raising.
    assert commercial_status(requires_credentials=["shopify"], workspace=None) == "ready_for_client_service"


def test_never_raises_on_credential_scope_failure(monkeypatch):
    monkeypatch.setattr(
        "backend.workspaces.credential_scope.scope_for",
        lambda ws: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    ws = ClientWorkspace(name="x")
    assert commercial_status(requires_credentials=["shopify"], workspace=ws) == "ready_for_dry_run"
