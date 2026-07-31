"""Tests for backend.workspaces.credential_scope.scope_for."""
import backend.config as config
from backend.workspaces.client_workspace import ClientWorkspace
from backend.workspaces.credential_scope import scope_for


class TestCredentialScopeConfigured:
    def test_configured_service_reports_configured(self, monkeypatch):
        monkeypatch.setattr(config, "list_configured_services", lambda: {"shopify": True, "meta": False})
        monkeypatch.setattr(config, "is_dry_run", lambda svc: False)
        ws = ClientWorkspace(name="x")

        scope = scope_for(ws)

        assert scope["shopify"]["status"] == "configured"
        assert scope["shopify"]["dry_run"] is False
        assert scope["meta_ads"]["status"] == "not_configured"

    def test_never_raises_when_config_lookup_fails(self, monkeypatch):
        def _boom():
            raise RuntimeError("config unavailable")
        monkeypatch.setattr(config, "list_configured_services", _boom)
        ws = ClientWorkspace(name="x")

        scope = scope_for(ws)  # must not raise
        assert isinstance(scope, dict)


class TestCredentialScopeUnsupported:
    def test_unsupported_integrations_never_report_configured(self, monkeypatch):
        monkeypatch.setattr(config, "list_configured_services", lambda: {})
        ws = ClientWorkspace(name="x")

        scope = scope_for(ws)

        for integration in ("crm", "whatsapp", "calendar", "content_scheduler", "suppliers"):
            assert scope[integration]["status"] == "not_yet_supported"


class TestCredentialScopeWorkspaceAllowList:
    def test_allowed_integrations_restricts_allowed_flag(self, monkeypatch):
        monkeypatch.setattr(config, "list_configured_services", lambda: {"shopify": True})
        ws = ClientWorkspace(name="x", allowed_integrations=["shopify"])

        scope = scope_for(ws)

        assert scope["shopify"]["allowed"] is True
        assert scope["meta_ads"]["allowed"] is False

    def test_empty_allow_list_means_no_restriction(self, monkeypatch):
        monkeypatch.setattr(config, "list_configured_services", lambda: {})
        ws = ClientWorkspace(name="x", allowed_integrations=[])

        scope = scope_for(ws)

        assert all(v["allowed"] for v in scope.values())
