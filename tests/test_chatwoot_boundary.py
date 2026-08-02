from backend.contracts.adapters import SidecarContext
from backend.integrations.chatwoot import ChatwootConversationAdapter


def test_health_unconfigured_without_env_vars(monkeypatch):
    monkeypatch.delenv("CHATWOOT_BASE_URL", raising=False)
    monkeypatch.delenv("CHATWOOT_API_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("CHATWOOT_ACCOUNT_ID", raising=False)
    health = ChatwootConversationAdapter().health()
    assert health.configured is False
    assert health.reachable is False


def test_create_contact_dry_run_makes_no_http_call():
    class Client:
        def request(self, *args, **kwargs):
            raise AssertionError("dry-run must not make HTTP calls")

    adapter = ChatwootConversationAdapter()
    adapter._client = Client()
    result = adapter.create_contact({"name": "Lead"}, context=SidecarContext(dry_run=True, idempotency_key="a"))
    assert result["dry_run"] is True


def test_send_message_draft_is_always_a_draft_never_sent():
    adapter = ChatwootConversationAdapter()
    result = adapter.send_message_draft("conv-1", {"text": "hi"}, context=SidecarContext(dry_run=False, approval_state="approved", idempotency_key="a"))
    assert result["status"] == "draft_pending_human_approval"


def test_handoff_requires_approval_when_live():
    import pytest
    adapter = ChatwootConversationAdapter()
    with pytest.raises(PermissionError):
        adapter.handoff_to_human("conv-1", context=SidecarContext(dry_run=False, idempotency_key="a"))
