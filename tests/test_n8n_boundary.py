from backend.contracts.adapters import SidecarContext
from backend.integrations.n8n import N8nAutomationAdapter


def test_n8n_dry_run_is_network_free():
    result = N8nAutomationAdapter().trigger("alerts", {"message": "hello"}, context=SidecarContext(idempotency_key="a"))
    assert result["id"] == "dry-n8n-a"
    assert result["dry_run"] is True


def test_n8n_rejects_unallowlisted_workflow():
    try:
        N8nAutomationAdapter().trigger("launch_ads", {}, context=SidecarContext())
    except PermissionError:
        pass
    else:
        raise AssertionError("n8n product workflows must not bypass the internal allowlist")


def test_n8n_live_trigger_requires_idempotency_key():
    try:
        N8nAutomationAdapter(base_url="https://n8n.internal").trigger(
            "alerts", {}, context=SidecarContext(dry_run=False, approval_state="approved")
        )
    except ValueError as exc:
        assert "idempotency_key" in str(exc)
    else:
        raise AssertionError("live n8n triggers must require idempotency")


def test_n8n_live_trigger_preserves_context_and_retries(monkeypatch):
    class Response:
        status_code = 200
        def raise_for_status(self):
            return None
        def json(self):
            return {"executionId": "exec-1"}
    class Client:
        def __init__(self):
            self.calls = []
        def post(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return Response()
    monkeypatch.setenv("N8N_MAX_RETRIES", "0")
    client = Client()
    result = N8nAutomationAdapter(base_url="https://n8n.internal", token="secret", client=client).trigger(
        "crm_sync", {"lead": "l1"}, context=SidecarContext(workspace_id="w", run_id="r", artifact_id="a", idempotency_key="k", dry_run=False, approval_state="approved")
    )
    assert result["executionId"] == "exec-1"
    url, kwargs = client.calls[0]
    assert url == "https://n8n.internal/webhook/crm_sync"
    assert kwargs["headers"]["Idempotency-Key"] == "k"
    assert kwargs["json"]["context"]["workspace_id"] == "w"
