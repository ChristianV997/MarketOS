"""Tests for backend.workspaces.live_mode_checklist.check."""
import backend.config as config
from backend.orchestration.event_store import event_store
from backend.workspaces import live_mode_checklist as lmc
from backend.workspaces.client_workspace import ClientWorkspace


class _FakeExperimentRegistry:
    def __init__(self, spend=0.0):
        self._spend = spend

    def spend_this_month(self, workspace_id, **kwargs):
        return self._spend


class TestLiveModeChecklistBlocks:
    def test_blocks_when_live_mode_disabled(self, monkeypatch):
        ws = ClientWorkspace(name="x", live_mode_enabled=False)
        result = lmc.check(ws, "shopify", proposed_amount=10.0)

        assert result["allowed"] is False
        assert any("live mode is disabled" in r for r in result["blocked_reasons"])

    def test_blocks_when_credentials_missing(self, monkeypatch):
        monkeypatch.setattr(config, "list_configured_services", lambda: {})
        ws = ClientWorkspace(name="x", live_mode_enabled=True, budget_ceiling_monthly=100, budget_ceiling_per_experiment=100)
        result = lmc.check(ws, "shopify", proposed_amount=10.0)

        assert result["allowed"] is False
        assert result["checklist"]["credential_configured"] is False

    def test_blocks_when_no_budget_ceilings_configured(self, monkeypatch):
        monkeypatch.setattr(config, "list_configured_services", lambda: {"shopify": True})
        ws = ClientWorkspace(name="x", live_mode_enabled=True)  # ceilings default to 0
        result = lmc.check(ws, "shopify", proposed_amount=10.0)

        assert result["allowed"] is False
        assert result["checklist"]["within_monthly_ceiling"] is False
        assert result["checklist"]["within_experiment_ceiling"] is False

    def test_blocks_when_proposed_amount_exceeds_experiment_ceiling(self, monkeypatch):
        monkeypatch.setattr(config, "list_configured_services", lambda: {"shopify": True})
        ws = ClientWorkspace(
            name="x", live_mode_enabled=True, allowed_integrations=["shopify"],
            budget_ceiling_monthly=1000.0, budget_ceiling_per_experiment=50.0,
        )
        result = lmc.check(ws, "shopify", proposed_amount=200.0)

        assert result["allowed"] is False
        assert result["checklist"]["within_experiment_ceiling"] is False


class TestLiveModeChecklistAllows:
    def test_allows_when_every_condition_met(self, monkeypatch):
        monkeypatch.setattr(config, "list_configured_services", lambda: {"shopify": True})
        monkeypatch.setattr(config, "is_dry_run", lambda svc: False)
        monkeypatch.setattr(
            "backend.experiments.registry.get_experiment_registry",
            lambda: _FakeExperimentRegistry(spend=0.0),
        )
        ws = ClientWorkspace(
            name="x", live_mode_enabled=True, allowed_integrations=["shopify"],
            budget_ceiling_monthly=1000.0, budget_ceiling_per_experiment=100.0,
        )
        result = lmc.check(ws, "shopify", proposed_amount=50.0)

        assert result["allowed"] is True
        assert result["blocked_reasons"] == []


class TestLiveModeChecklistJournaling:
    def test_shadow_journal_always_written(self, monkeypatch):
        ws = ClientWorkspace(name="x", live_mode_enabled=False)
        lmc.check(ws, "shopify", proposed_amount=1.0)

        events = [e for e in event_store._iter_events() if e.get("event") == "shadow_live_mode_checklist"]
        assert events
        assert events[-1]["data"]["allowed"] is False
        assert "checklist" in events[-1]["data"]

    def test_journal_written_even_on_allowed_result(self, monkeypatch):
        monkeypatch.setattr(config, "list_configured_services", lambda: {"shopify": True})
        monkeypatch.setattr(config, "is_dry_run", lambda svc: False)
        monkeypatch.setattr(
            "backend.experiments.registry.get_experiment_registry",
            lambda: _FakeExperimentRegistry(spend=0.0),
        )
        ws = ClientWorkspace(
            name="x", live_mode_enabled=True, allowed_integrations=["shopify"],
            budget_ceiling_monthly=1000.0, budget_ceiling_per_experiment=100.0,
        )
        lmc.check(ws, "shopify", proposed_amount=50.0)

        events = [e for e in event_store._iter_events() if e.get("event") == "shadow_live_mode_checklist"]
        assert events
        assert events[-1]["data"]["allowed"] is True


class TestModeIsOrthogonalToLiveGate:
    """ClientWorkspace.mode is a commercial-maturity label, not a live/
    dry-run gate — see the docstring on backend.workspaces.client_workspace's
    MODES constant and docs/LIVE_MODE_SAFETY.md. This is a deliberate design
    decision, not an oversight: the checklist's result must depend only on
    live_mode_enabled/credentials/budget, never on `mode`."""

    def test_full_saas_mode_still_blocked_without_live_mode_enabled(self, monkeypatch):
        monkeypatch.setattr(config, "list_configured_services", lambda: {"shopify": True})
        ws = ClientWorkspace(
            name="x", mode="full_saas", live_mode_enabled=False,
            allowed_integrations=["shopify"], budget_ceiling_monthly=1000.0,
            budget_ceiling_per_experiment=100.0,
        )
        result = lmc.check(ws, "shopify", proposed_amount=50.0)
        assert result["allowed"] is False

    def test_internal_own_store_mode_can_still_be_allowed(self, monkeypatch):
        monkeypatch.setattr(config, "list_configured_services", lambda: {"shopify": True})
        monkeypatch.setattr(config, "is_dry_run", lambda svc: False)
        monkeypatch.setattr(
            "backend.experiments.registry.get_experiment_registry",
            lambda: _FakeExperimentRegistry(spend=0.0),
        )
        ws = ClientWorkspace(
            name="x", mode="internal_own_store", live_mode_enabled=True,
            allowed_integrations=["shopify"], budget_ceiling_monthly=1000.0,
            budget_ceiling_per_experiment=100.0,
        )
        result = lmc.check(ws, "shopify", proposed_amount=50.0)
        assert result["allowed"] is True

    def test_result_mode_field_reflects_workspace_mode_for_reporting_only(self, monkeypatch):
        ws = ClientWorkspace(name="x", mode="saas_lite", live_mode_enabled=False)
        result = lmc.check(ws, "shopify", proposed_amount=1.0)
        assert result["mode"] == "saas_lite"  # carried through for context, not used as a gate input


class TestLiveModeChecklistNeverRaises:
    def test_never_raises_on_garbage_integration(self, monkeypatch):
        ws = ClientWorkspace(name="x")
        result = lmc.check(ws, "totally-unknown-integration-xyz", proposed_amount=-999.0)
        assert isinstance(result, dict)
        assert result["allowed"] is False

    def test_never_raises_when_scope_for_fails(self, monkeypatch):
        monkeypatch.setattr("backend.workspaces.live_mode_checklist.scope_for", lambda ws: (_ for _ in ()).throw(RuntimeError("boom")))
        ws = ClientWorkspace(name="x", live_mode_enabled=True)
        result = lmc.check(ws, "shopify", proposed_amount=1.0)
        assert result["allowed"] is False
        assert any("live_mode_checklist_error" in r for r in result["blocked_reasons"])
