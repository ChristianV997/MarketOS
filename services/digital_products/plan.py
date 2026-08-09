"""services.digital_products.plan — build_digital_product_plan, the
top-level entrypoint tying offer/funnel/content-plan/validation/checklist
together into one CommercialRunEnvelope-backed result."""
from __future__ import annotations

from backend.experiments.audit_log import log_transition
from backend.experiments.envelope import CommercialRunEnvelope
from backend.experiments.registry import get_experiment_registry
from backend.workspaces.artifact_store import ArtifactStore
from backend.workspaces.client_workspace import ClientWorkspace

from .checklist import build_launch_checklist
from .content_plan import generate_content_plan
from .economics import estimate_digital_product_margin
from .funnel import build_funnel_plan
from .offer import create_digital_offer
from .schemas import DigitalProductPlan
from .validation import validate_digital_product

SERVICE_NAME = "digital_products"

_DEFAULT_METRICS = ["visitors", "lead-magnet opt-in rate", "checkout conversion rate", "refund rate", "CAC (if paid traffic used)"]


def _default_workspace() -> ClientWorkspace:
    return ClientWorkspace(name="ephemeral", workspace_type="internal")


def build_digital_product_plan(
    offer_name: str,
    *,
    product_type: str = "playbook",
    target_customer: str = "",
    transformation_promised: str = "",
    price: float = 0.0,
    target_buyers: int = 10,
    has_existing_audience: bool = False,
    workspace: ClientWorkspace | None = None,
) -> tuple[DigitalProductPlan, CommercialRunEnvelope]:
    """Never raises: every function above is individually fail-soft."""
    workspace = workspace or _default_workspace()
    registry = get_experiment_registry()
    store = ArtifactStore()

    envelope = CommercialRunEnvelope(
        service_name=SERVICE_NAME,
        workspace_id=workspace.workspace_id,
        mode="dry_run" if workspace.dry_run_default else workspace.mode,
        inputs={"offer_name": offer_name, "product_type": product_type, "price": price},
    )
    registry.register(envelope)
    log_transition(envelope, "experiment_created")
    envelope.mark_running()

    offer = create_digital_offer(
        offer_name, product_type=product_type, target_customer=target_customer,
        transformation_promised=transformation_promised, price=price,
    )
    funnel = build_funnel_plan(offer)
    content_plan = generate_content_plan(offer)
    validation = validate_digital_product(offer, target_buyers=target_buyers, has_existing_audience=has_existing_audience)
    margin = estimate_digital_product_margin(price)
    checklist = build_launch_checklist(offer, funnel, validation)

    decision_criteria = {
        "kill": "validation verdict is unsafe, or 3+ launch attempts with <1% checkout conversion",
        "iterate": "validation verdict is fragile — narrow the offer or target a smaller/warmer audience first",
        "scale": "validation verdict is viable/strong AND at least one real launch cleared target_buyers",
    }

    result = DigitalProductPlan(
        offer=offer.to_dict(), funnel=funnel.to_dict(), content_plan=content_plan,
        validation=validation.to_dict(), margin=margin, launch_checklist=checklist,
        metrics_to_track=list(_DEFAULT_METRICS), decision_criteria=decision_criteria,
        dry_run=workspace.dry_run_default,
    )

    try:
        from services.reporting import save_report_artifacts
        from .report import render_digital_product_markdown
        save_report_artifacts(store, workspace.workspace_id, envelope.experiment_id,
                               render_digital_product_markdown(result), result.to_dict())
    except Exception:  # noqa: BLE001 — the JSON result below is the durable fallback
        store.save(workspace.workspace_id, envelope.experiment_id, "result.json", result.to_dict())

    envelope.mark_completed(result.to_dict())
    log_transition(envelope, "experiment_completed")

    return result, envelope
