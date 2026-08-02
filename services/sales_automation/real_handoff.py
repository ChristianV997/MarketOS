"""Explicitly gated Chatwoot record-keeping for sales simulations.

Qualification remains local and deterministic.  This module only mirrors an
already-computed handoff into Chatwoot: contact/conversation creation,
transcript backfill, a human-review draft, and (when the existing session
decision already handed off) a human handoff.  It never sends a customer
message and never makes a second qualification decision.
"""
from __future__ import annotations

import os
from typing import Any, Callable

from backend.contracts.adapters import SidecarContext
from backend.integrations.chatwoot import conversation_provider_chatwoot
from backend.workspaces.client_workspace import ClientWorkspace
from backend.workspaces.credential_scope import scope_for

from .schemas import AppointmentHandoff, ChatSession


def _id(result: Any) -> str:
    if isinstance(result, dict):
        value = result.get("id") or result.get("conversation_id")
        return str(value) if value else ""
    return ""


def _gate_open(*, attempt_real_handoff: bool, workspace: ClientWorkspace) -> bool:
    """Require every explicit live-recording condition before any adapter call."""
    if not attempt_real_handoff or workspace.dry_run_default:
        return False
    try:
        status = scope_for(workspace).get("conversation_provider_chatwoot", {})
        return (
            status.get("status") == "configured"
            and status.get("dry_run") is False
            and status.get("allowed") is True
        )
    except Exception:
        return False


def attempt_real_conversation_handoff(
    session: ChatSession,
    handoff: AppointmentHandoff,
    *,
    workspace: ClientWorkspace,
    envelope_id: str,
    attempt_real_handoff: bool = False,
) -> dict[str, Any] | None:
    """Mirror a qualified session to Chatwoot only after explicit opt-in.

    Each provider operation is isolated so a partial outage is returned as a
    structured result instead of aborting the simulation.  The shared live
    mode checklist is intentionally not reused: it is spend-shaped and would
    incorrectly require a budget ceiling for this non-monetary, draft-only
    workflow.  A future generalized checklist can unify these gates.
    """
    if not _gate_open(attempt_real_handoff=attempt_real_handoff, workspace=workspace):
        return None

    context = SidecarContext(
        workspace_id=workspace.workspace_id,
        run_id=envelope_id,
        artifact_id=envelope_id,
        parent_ids=(session.session_id,),
        idempotency_key=f"sales_automation:{session.session_id}",
        dry_run=False,
        approval_state="approved",
    )
    operations: dict[str, Any] = {}
    contact_id = ""
    conversation_id = ""

    def attempt(name: str, call: Callable[[], Any]) -> Any:
        try:
            result = call()
            operations[name] = {"status": "completed", "result": result}
            return result
        except Exception as exc:  # noqa: BLE001 - external sidecar boundary
            operations[name] = {"status": "failed", "error": str(exc)}
            return None

    contact = attempt(
        "create_contact",
        lambda: conversation_provider_chatwoot.create_contact(
            {
                "name": f"MarketOS lead {session.session_id}",
                "identifier": session.session_id,
                "custom_attributes": {
                    "vertical": session.vertical,
                    "qualification_slots": session.slots.to_dict(),
                    "workspace_id": workspace.workspace_id,
                },
            },
            context=context,
        ),
    )
    contact_id = _id(contact)

    conversation_payload: dict[str, Any] = {
        "contact_id": contact_id,
        "status": "open",
        "custom_attributes": {
            "marketos_envelope_id": envelope_id,
            "session_id": session.session_id,
            "vertical": session.vertical,
        },
    }
    inbox_id = os.getenv("CHATWOOT_INBOX_ID", "")
    if inbox_id:
        conversation_payload["inbox_id"] = inbox_id
    conversation = attempt(
        "create_conversation",
        lambda: conversation_provider_chatwoot.create_conversation(conversation_payload, context=context),
    )
    conversation_id = _id(conversation)

    transcript = "\n".join(f"{turn.speaker}: {turn.message}" for turn in session.turns)
    if conversation_id:
        attempt(
            "record_inbound_message",
            lambda: conversation_provider_chatwoot.record_inbound_message(
                conversation_id,
                {"content": transcript, "message_type": "incoming", "private": True},
                context=context,
            ),
        )
        attempt(
            "send_message_draft",
            lambda: conversation_provider_chatwoot.send_message_draft(
                conversation_id,
                {
                    "content": handoff.recommended_human_action,
                    "message_type": "outgoing",
                    "private": True,
                },
                context=context,
            ),
        )
        if session.handed_off:
            attempt(
                "handoff_to_human",
                lambda: conversation_provider_chatwoot.handoff_to_human(conversation_id, context=context),
            )
    else:
        operations["record_inbound_message"] = {"status": "skipped", "reason": "conversation_id_unavailable"}
        operations["send_message_draft"] = {"status": "skipped", "reason": "conversation_id_unavailable"}
        if session.handed_off:
            operations["handoff_to_human"] = {"status": "skipped", "reason": "conversation_id_unavailable"}

    failed = [item for item in operations.values() if item.get("status") == "failed"]
    return {
        "attempted": True,
        "status": "partial_failure" if failed else "completed",
        "draft_only": True,
        "contact_id": contact_id,
        "conversation_id": conversation_id,
        "operations": operations,
    }
