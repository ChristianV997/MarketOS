from __future__ import annotations

import json

from backend.workspaces.client_workspace import ClientWorkspace
from services.sales_automation.appointment_flow import create_appointment_handoff
from services.sales_automation.real_handoff import attempt_real_conversation_handoff
from services.sales_automation.schemas import ChatSession


def _workspace() -> ClientWorkspace:
    return ClientWorkspace(name="real-handoff-test", dry_run_default=False)


def _session(*, handed_off: bool = False) -> ChatSession:
    session = ChatSession(session_id="session-1", vertical="car_sales", handed_off=handed_off)
    session.handoff_reason = "qualified"
    return session


def _open_gate(monkeypatch, provider):
    import services.sales_automation.real_handoff as module
    monkeypatch.setattr(module, "conversation_provider_chatwoot", provider)
    monkeypatch.setattr(
        module,
        "scope_for",
        lambda workspace: {"conversation_provider_chatwoot": {"status": "configured", "dry_run": False, "allowed": True}},
    )


def test_exception_leakage_is_prevented(monkeypatch):
    # Canary text that should not appear in any output
    canary = "SECRET_TOKEN=sk-live-synthetic-canary"
    provider = type("Provider", (), {"create_contact": lambda self, payload, *, context: (_ for _ in ()).throw(RuntimeError(canary))})()
    _open_gate(monkeypatch, provider)
    session = _session()
    result = attempt_real_conversation_handoff(
        session,
        create_appointment_handoff(session),
        workspace=_workspace(),
        envelope_id="env-1",
        attempt_real_handoff=True,
    )
    assert result["status"] == "partial_failure"
    # Ensure generic error code is used
    assert result["operations"]["create_contact"]["error"] == "provider_call_failed"
    # Ensure the canary does not appear in the JSON representation
    dumped = json.dumps(result)
    assert canary not in dumped
