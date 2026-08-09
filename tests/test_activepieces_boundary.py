import pytest

from backend.contracts.adapters import SidecarContext
from backend.integrations.activepieces import ActivepiecesAutomationAdapter


def test_health_unconfigured_without_env_vars(monkeypatch):
    monkeypatch.delenv("ACTIVEPIECES_BASE_URL", raising=False)
    monkeypatch.delenv("ACTIVEPIECES_API_KEY", raising=False)
    health = ActivepiecesAutomationAdapter().health()
    assert health.configured is False


def test_trigger_workflow_dry_run_makes_no_http_call():
    class Client:
        def request(self, *args, **kwargs):
            raise AssertionError("dry-run must not make HTTP calls")

    adapter = ActivepiecesAutomationAdapter(client=Client())
    result = adapter.trigger_workflow("flow-1", {"lead": "x"}, context=SidecarContext(dry_run=True, idempotency_key="a"))
    assert result["dry_run"] is True


def test_trigger_workflow_requires_approval_when_live():
    adapter = ActivepiecesAutomationAdapter()
    with pytest.raises(PermissionError):
        adapter.trigger_workflow("flow-1", {}, context=SidecarContext(dry_run=False, idempotency_key="a"))


def test_list_available_workflows_unconfigured_raises():
    adapter = ActivepiecesAutomationAdapter()
    with pytest.raises(RuntimeError):
        adapter.list_available_workflows()
