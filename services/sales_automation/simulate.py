"""services.sales_automation.simulate — run_sales_bot_simulation.

Drives a full scripted conversation locally and produces an appointment
handoff — the "local simulation adapter" the task explicitly calls for
instead of any real outbound messaging integration. Tied to a
CommercialRunEnvelope like every other service module, for a consistent
audit trail even though nothing here is money-adjacent.
"""
from __future__ import annotations

from backend.experiments.audit_log import log_transition
from backend.experiments.envelope import CommercialRunEnvelope
from backend.experiments.registry import get_experiment_registry
from backend.workspaces.artifact_store import ArtifactStore
from backend.workspaces.client_workspace import ClientWorkspace

from .appointment_flow import create_appointment_handoff, handle_chat_turn
from .follow_up import generate_follow_up_sequence
from .qualification import generate_qualification_flow
from .schemas import AppointmentHandoff, ChatSession

SERVICE_NAME = "sales_automation"


def _default_workspace() -> ClientWorkspace:
    return ClientWorkspace(name="ephemeral", workspace_type="internal")


def run_simulated_conversation(vertical: str, scripted_lead_messages: list[str]) -> ChatSession:
    """Never raises. Drives `scripted_lead_messages` through handle_chat_turn
    one at a time, stopping early once the session is handed off."""
    session = ChatSession(vertical=vertical)
    for message in scripted_lead_messages:
        if session.handed_off:
            break
        handle_chat_turn(session, message)
    return session


def run_sales_bot_simulation(
    vertical: str,
    scripted_lead_messages: list[str],
    *,
    workspace: ClientWorkspace | None = None,
    attempt_real_handoff: bool = False,
) -> tuple[ChatSession, AppointmentHandoff, list[str], CommercialRunEnvelope]:
    """Never raises. Returns (session, handoff, qualification_flow, envelope)."""
    workspace = workspace or _default_workspace()
    registry = get_experiment_registry()
    store = ArtifactStore()

    envelope = CommercialRunEnvelope(
        service_name=SERVICE_NAME,
        workspace_id=workspace.workspace_id,
        mode="dry_run" if workspace.dry_run_default else workspace.mode,
        inputs={"vertical": vertical, "scripted_lead_messages": scripted_lead_messages},
    )
    registry.register(envelope)
    log_transition(envelope, "experiment_created")
    envelope.mark_running()

    qualification_flow = generate_qualification_flow(vertical)
    session = run_simulated_conversation(vertical, scripted_lead_messages)
    handoff = create_appointment_handoff(session)
    follow_up = generate_follow_up_sequence(session) if not session.handed_off else []

    from services.sales_automation.real_handoff import attempt_real_conversation_handoff
    from services.status import commercial_status

    real_handoff = attempt_real_conversation_handoff(
        session,
        handoff,
        workspace=workspace,
        envelope_id=envelope.experiment_id,
        attempt_real_handoff=attempt_real_handoff,
    )

    outputs = {
        "session": session.to_dict(),
        "handoff": handoff.to_dict(),
        "qualification_flow": qualification_flow,
        "follow_up_sequence": follow_up,
        "real_handoff": real_handoff,
        "commercial_status": commercial_status(
            requires_credentials=["conversation_provider_chatwoot"], workspace=workspace,
        ),
    }
    try:
        from services.reporting import save_report_artifacts
        from .report import render_sales_bot_setup_plan_markdown
        markdown = render_sales_bot_setup_plan_markdown(session, handoff, qualification_flow, dry_run=workspace.dry_run_default)
        save_report_artifacts(store, workspace.workspace_id, envelope.experiment_id, markdown, outputs)
    except Exception:  # noqa: BLE001 — the JSON result below is the durable fallback
        store.save(workspace.workspace_id, envelope.experiment_id, "result.json", outputs)

    envelope.mark_completed(outputs)
    log_transition(envelope, "experiment_completed")

    return session, handoff, qualification_flow, envelope
