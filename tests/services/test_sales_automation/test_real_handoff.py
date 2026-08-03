"""Tests for services.sales_automation.real_handoff."""
import pytest
from backend.contracts.adapters import AdapterHealth
from backend.workspaces.client_workspace import ClientWorkspace
from services.sales_automation.appointment_flow import create_appointment_handoff, handle_chat_turn
from services.sales_automation.real_handoff import INTEGRATION_KEY, attempt_real_conversation_handoff
from services.sales_automation.schemas import ChatSession


def _session(*, handed_off: bool = False) -> ChatSession:
    session = ChatSession(vertical="real_estate")
    handle_chat_turn(session, "I'm looking to buy a house in Austin")
    handle_chat_turn(session, "asap, budget is $500,000, in Austin")
    session.handed_off = handed_off
    return session


class _FakeProvider:
    """Records every call; lets a test force any method to raise."""

    def __init__(self, *, raise_on: set[str] = frozenset()):
        self.raise_on = raise_on
        self.calls: list[str] = []

    def _maybe_raise(self, name: str) -> None:
        self.calls.append(name)
        if name in self.raise_on:
            raise RuntimeError(f"{name} failed")

    def health(self) -> AdapterHealth:
        return AdapterHealth("fake", configured=True, reachable=True)

    def create_contact(self, contact, *, context):
        self._maybe_raise("create_contact")
        return {"id": "contact-1"}

    def create_conversation(self, conversation, *, context):
        self._maybe_raise("create_conversation")
        return {"id": "conversation-1"}

    def send_message_draft(self, conversation_id, message, *, context):
        self._maybe_raise("send_message_draft")
        return {"id": "draft-1", "status": "draft_pending_human_approval"}

    def record_inbound_message(self, conversation_id, message, *, context):
        self._maybe_raise("record_inbound_message")
        return {"ok": True}

    def handoff_to_human(self, conversation_id, *, context):
        self._maybe_raise("handoff_to_human")
        return {"status": "handed_off"}


def _live_workspace() -> ClientWorkspace:
    return ClientWorkspace(name="live-tenant", dry_run_default=False)


def _configured_scope(monkeypatch, *, allowed: bool = True, dry_run: bool = False, status: str = "configured"):
    import services.sales_automation.real_handoff as real_handoff_module

    def fake_scope_for(workspace):
        return {INTEGRATION_KEY: {"status": status, "allowed": allowed, "dry_run": dry_run}}

    monkeypatch.setattr(real_handoff_module, "scope_for", fake_scope_for)


class TestGateClosedByDefault:
    def test_not_attempted_returns_none(self):
        session = _session()
        handoff = create_appointment_handoff(session)
        result = attempt_real_conversation_handoff(
            session, handoff, workspace=_live_workspace(), envelope_id="env-1",
            attempt_real_handoff=False, provider=_FakeProvider(),
        )
        assert result is None

    def test_dry_run_workspace_returns_none_even_if_attempted(self):
        session = _session()
        handoff = create_appointment_handoff(session)
        workspace = ClientWorkspace(name="dry-tenant")  # dry_run_default=True
        result = attempt_real_conversation_handoff(
            session, handoff, workspace=workspace, envelope_id="env-1",
            attempt_real_handoff=True, provider=_FakeProvider(),
        )
        assert result is None

    def test_unconfigured_credential_returns_none(self):
        session = _session()
        handoff = create_appointment_handoff(session)
        # Real scope_for (no monkeypatch): Chatwoot env vars are unset in
        # tests, so this reports not_configured — gate stays closed.
        result = attempt_real_conversation_handoff(
            session, handoff, workspace=_live_workspace(), envelope_id="env-1",
            attempt_real_handoff=True, provider=_FakeProvider(),
        )
        assert result is None


class TestGateOpen:
    def test_creates_contact_conversation_and_draft(self, monkeypatch):
        _configured_scope(monkeypatch)
        session = _session()
        handoff = create_appointment_handoff(session)
        provider = _FakeProvider()
        result = attempt_real_conversation_handoff(
            session, handoff, workspace=_live_workspace(), envelope_id="env-1",
            attempt_real_handoff=True, provider=provider,
        )
        assert result["attempted"] is True
        assert result["contact"] == {"id": "contact-1"}
        assert result["conversation"] == {"id": "conversation-1"}
        assert result["transcript_recorded"] == 2  # both lead turns
        assert result["draft"]["status"] == "draft_pending_human_approval"
        assert result["errors"] == []

    def test_draft_is_always_a_draft_regression_guard(self, monkeypatch):
        _configured_scope(monkeypatch)
        session = _session()
        handoff = create_appointment_handoff(session)
        result = attempt_real_conversation_handoff(
            session, handoff, workspace=_live_workspace(), envelope_id="env-1",
            attempt_real_handoff=True, provider=_FakeProvider(),
        )
        assert result["draft"]["status"] == "draft_pending_human_approval"

    def test_handoff_to_human_only_fires_when_session_handed_off(self, monkeypatch):
        _configured_scope(monkeypatch)
        handoff_session = _session(handed_off=True)
        handoff = create_appointment_handoff(handoff_session)
        provider = _FakeProvider()
        result = attempt_real_conversation_handoff(
            handoff_session, handoff, workspace=_live_workspace(), envelope_id="env-1",
            attempt_real_handoff=True, provider=provider,
        )
        assert result["handed_off"] is True
        assert "handoff_to_human" in provider.calls

    def test_handoff_to_human_skipped_when_not_handed_off(self, monkeypatch):
        _configured_scope(monkeypatch)
        session = _session(handed_off=False)
        handoff = create_appointment_handoff(session)
        provider = _FakeProvider()
        result = attempt_real_conversation_handoff(
            session, handoff, workspace=_live_workspace(), envelope_id="env-1",
            attempt_real_handoff=True, provider=provider,
        )
        assert result["handed_off"] is False
        assert "handoff_to_human" not in provider.calls

    def test_never_raises_on_adapter_failure(self, monkeypatch):
        _configured_scope(monkeypatch)
        session = _session(handed_off=True)
        handoff = create_appointment_handoff(session)
        provider = _FakeProvider(raise_on={"create_contact", "create_conversation", "send_message_draft", "handoff_to_human"})
        result = attempt_real_conversation_handoff(
            session, handoff, workspace=_live_workspace(), envelope_id="env-1",
            attempt_real_handoff=True, provider=provider,
        )
        # create_conversation still raises but was still attempted even
        # though create_contact failed — one failure doesn't abort the rest.
        assert result["contact"] is None
        assert any("create_contact" in e for e in result["errors"])

    def test_partial_failure_does_not_abort_remaining_steps(self, monkeypatch):
        _configured_scope(monkeypatch)
        session = _session(handed_off=True)
        handoff = create_appointment_handoff(session)
        provider = _FakeProvider(raise_on={"send_message_draft"})
        result = attempt_real_conversation_handoff(
            session, handoff, workspace=_live_workspace(), envelope_id="env-1",
            attempt_real_handoff=True, provider=provider,
        )
        assert result["contact"] == {"id": "contact-1"}
        assert result["conversation"] == {"id": "conversation-1"}
        assert result["draft"] is None
        assert any("send_message_draft" in e for e in result["errors"])
        # handoff_to_human still attempted despite the draft failure
        assert result["handed_off"] is True
