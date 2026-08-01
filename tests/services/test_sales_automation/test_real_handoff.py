from __future__ import annotations

from backend.workspaces.client_workspace import ClientWorkspace
from services.sales_automation.appointment_flow import create_appointment_handoff
from services.sales_automation.real_handoff import attempt_real_conversation_handoff
from services.sales_automation.schemas import ChatSession


class FakeConversationProvider:
    def __init__(self):
        self.calls = []

    def create_contact(self, payload, *, context):
        self.calls.append(("contact", payload, context))
        return {"id": "contact-1"}

    def create_conversation(self, payload, *, context):
        self.calls.append(("conversation", payload, context))
        return {"id": "conversation-1"}

    def record_inbound_message(self, conversation_id, payload, *, context):
        self.calls.append(("inbound", conversation_id, payload, context))
        return {"id": "message-1"}

    def send_message_draft(self, conversation_id, payload, *, context):
        self.calls.append(("draft", conversation_id, payload, context))
        return {"status": "draft_pending_human_approval"}

    def handoff_to_human(self, conversation_id, *, context):
        self.calls.append(("handoff", conversation_id, context))
        return {"status": "handed_off"}


def _workspace() -> ClientWorkspace:
    return ClientWorkspace(name="real-handoff-test", dry_run_default=False)


def _session(*, handed_off: bool = True) -> ChatSession:
    session = ChatSession(session_id="session-1", vertical="car_sales", handed_off=handed_off)
    session.handoff_reason = "qualified"
    return session


def _open_gate(monkeypatch, provider):
    import services.sales_automation.real_handoff as module
    monkeypatch.setattr(module, "conversation_provider_chatwoot", provider)
    monkeypatch.setattr(
        module,
        "scope_for",
        lambda workspace: {
            "conversation_provider_chatwoot": {
                "status": "configured", "dry_run": False, "allowed": True,
            }
        },
    )


def test_gate_closed_by_default(monkeypatch):
    provider = FakeConversationProvider()
    _open_gate(monkeypatch, provider)
    result = attempt_real_conversation_handoff(
        _session(), create_appointment_handoff(_session()),
        workspace=_workspace(), envelope_id="env-1",
    )
    assert result is None
    assert provider.calls == []


def test_open_gate_creates_contact_conversation_and_draft(monkeypatch):
    provider = FakeConversationProvider()
    _open_gate(monkeypatch, provider)
    session = _session(handed_off=False)
    result = attempt_real_conversation_handoff(
        session, create_appointment_handoff(session), workspace=_workspace(),
        envelope_id="env-1", attempt_real_handoff=True,
    )
    assert result["status"] == "completed"
    assert result["draft_only"] is True
    assert [call[0] for call in provider.calls] == ["contact", "conversation", "inbound", "draft"]
    assert provider.calls[-1][2]["message_type"] == "outgoing"
    assert provider.calls[0][2].dry_run is False
    assert provider.calls[0][2].approval_state == "approved"
    assert provider.calls[0][2].idempotency_key == "sales_automation:session-1"


def test_handoff_only_follows_existing_session_decision(monkeypatch):
    provider = FakeConversationProvider()
    _open_gate(monkeypatch, provider)
    session = _session(handed_off=True)
    result = attempt_real_conversation_handoff(
        session, create_appointment_handoff(session), workspace=_workspace(),
        envelope_id="env-1", attempt_real_handoff=True,
    )
    assert result["status"] == "completed"
    assert [call[0] for call in provider.calls] == ["contact", "conversation", "inbound", "draft", "handoff"]


def test_adapter_failure_is_returned_without_raising(monkeypatch):
    provider = FakeConversationProvider()
    provider.create_contact = lambda payload, *, context: (_ for _ in ()).throw(RuntimeError("down"))
    _open_gate(monkeypatch, provider)
    session = _session(handed_off=False)
    result = attempt_real_conversation_handoff(
        session, create_appointment_handoff(session), workspace=_workspace(),
        envelope_id="env-1", attempt_real_handoff=True,
    )
    assert result["status"] == "partial_failure"
    assert result["operations"]["create_contact"]["status"] == "failed"
