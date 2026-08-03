"""services.sales_automation.real_handoff — attempt_real_conversation_handoff.

Optional, explicitly-gated bridge from the simulation-only qualification
flow (appointment_flow.py) to a real ConversationProvider
(backend.integrations.chatwoot.conversation_provider_chatwoot). Mirrors the
existing `confirm_live` precedent in backend/api.py and the
`live_action_requested` flag in
services/ecommerce_operator/launch_guard.py: a real attempt requires an
explicit opt-in on top of dry_run=False and a configured, allowed
credential — it is not enough for the workspace to merely be live.

Deliberately does not reuse backend.workspaces.live_mode_checklist.check():
that gate is spend/budget-ceiling-shaped and would wrongly block a
non-monetary conversation action. Generalizing it with an optional
requires_budget_ceiling flag is a reasonable future unification, but is out
of scope here since it would touch a shared safety gate, not just this
module.

This module never makes an independent handoff-to-human decision —
`handoff_to_human` only fires when `session.handed_off` is already True
from appointment_flow.py's existing logic. `send_message_draft` always
returns a draft pending human approval per ConversationProvider's own
Protocol contract; this module never gains a live-send path.
"""
from __future__ import annotations

from typing import Any

from backend.contracts.adapters import ConversationProvider, SidecarContext
from backend.integrations.chatwoot import conversation_provider_chatwoot
from backend.workspaces.client_workspace import ClientWorkspace
from backend.workspaces.credential_scope import scope_for

from .schemas import AppointmentHandoff, ChatSession

INTEGRATION_KEY = "conversation_provider_chatwoot"


def _gate_open(workspace: ClientWorkspace, *, attempt_real_handoff: bool) -> bool:
    if not attempt_real_handoff or workspace.dry_run_default:
        return False
    try:
        scope = scope_for(workspace).get(INTEGRATION_KEY, {})
    except Exception:
        return False
    return scope.get("status") == "configured" and scope.get("dry_run") is False and scope.get("allowed") is True


def attempt_real_conversation_handoff(
    session: ChatSession,
    handoff: AppointmentHandoff,
    *,
    workspace: ClientWorkspace,
    envelope_id: str,
    attempt_real_handoff: bool = False,
    provider: ConversationProvider | None = None,
) -> dict[str, Any] | None:
    """Never raises. Returns None when the gate is closed (not attempted) —
    the caller's default behavior stays byte-identical to simulation-only.
    When attempted, each provider call is independently try/excepted so one
    failure doesn't abort the rest; errors are collected, not raised."""
    if not _gate_open(workspace, attempt_real_handoff=attempt_real_handoff):
        return None

    provider = provider or conversation_provider_chatwoot
    context = SidecarContext(
        workspace_id=workspace.workspace_id,
        run_id=envelope_id,
        idempotency_key=f"sales_automation:{session.session_id}",
        dry_run=False,
        approval_state="approved",
    )

    result: dict[str, Any] = {
        "attempted": True,
        "contact": None,
        "conversation": None,
        "transcript_recorded": 0,
        "draft": None,
        "handed_off": False,
        "errors": [],
    }

    contact_id = None
    try:
        contact = provider.create_contact(
            {"identifier": session.session_id, "name": session.session_id, "vertical": session.vertical},
            context=context,
        )
        result["contact"] = dict(contact)
        contact_id = contact.get("id")
    except Exception as exc:  # noqa: BLE001 — never abort the rest of the handoff
        result["errors"].append(f"create_contact: {exc}")

    conversation_id = None
    try:
        conversation = provider.create_conversation(
            {"contact_id": contact_id, "vertical": session.vertical}, context=context,
        )
        result["conversation"] = dict(conversation)
        conversation_id = conversation.get("id")
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"create_conversation: {exc}")

    if conversation_id is None:
        return result

    for turn in session.turns:
        if turn.speaker != "lead":
            continue
        try:
            provider.record_inbound_message(conversation_id, {"content": turn.message, "ts": turn.ts}, context=context)
            result["transcript_recorded"] += 1
        except Exception as exc:  # noqa: BLE001
            result["errors"].append(f"record_inbound_message: {exc}")

    try:
        draft = provider.send_message_draft(conversation_id, {"content": handoff.transcript_summary}, context=context)
        result["draft"] = dict(draft)
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"send_message_draft: {exc}")

    if session.handed_off:
        try:
            provider.handoff_to_human(conversation_id, context=context)
            result["handed_off"] = True
        except Exception as exc:  # noqa: BLE001
            result["errors"].append(f"handoff_to_human: {exc}")

    return result
