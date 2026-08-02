"""Vendor-neutral contracts for MarketOS OSS adapters and sidecars."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Protocol, Sequence


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class SidecarContext:
    workspace_id: str = "default"
    run_id: str = ""
    artifact_id: str = ""
    parent_ids: tuple[str, ...] = ()
    idempotency_key: str = ""
    dry_run: bool = True
    approval_state: str = "not_required"
    research_only: bool | None = None

    def to_headers(self) -> dict[str, str]:
        """Return the canonical lineage and safety headers for sidecars."""
        headers = {
            "X-MarketOS-Workspace": self.workspace_id,
            "X-MarketOS-Run": self.run_id,
            "X-MarketOS-Artifact": self.artifact_id,
            "X-MarketOS-Parents": ",".join(self.parent_ids),
            "X-MarketOS-Approval": self.approval_state,
        }
        if self.idempotency_key:
            headers["Idempotency-Key"] = self.idempotency_key
        return headers

    def require_live_idempotency(self) -> None:
        """Reject live sidecar mutations that cannot be safely retried."""
        from backend.research.mode import require_write_allowed

        require_write_allowed(
            dry_run=self.dry_run,
            approval_state=self.approval_state,
            action="sidecar_mutation",
        )
        if not self.idempotency_key:
            raise ValueError("live sidecar operations require an idempotency_key")


@dataclass(frozen=True)
class AdapterHealth:
    name: str
    configured: bool
    reachable: bool
    capabilities: tuple[str, ...] = ()
    observed_at: datetime = field(default_factory=_now)
    detail: str = ""


@dataclass(frozen=True)
class AdapterError:
    adapter: str
    code: str
    message: str
    retryable: bool = False
    status_code: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


class CommerceProvider(Protocol):
    def health(self) -> AdapterHealth: ...

    def list_products(self, *, limit: int = 50) -> Sequence[Mapping[str, Any]]: ...

    def get_inventory(self, product_ids: Sequence[str]) -> Sequence[Mapping[str, Any]]: ...

    def create_order(self, order: Mapping[str, Any], *, context: SidecarContext) -> Mapping[str, Any]: ...

    def create_cart(self, cart: Mapping[str, Any], *, context: SidecarContext) -> Mapping[str, Any]: ...

    def complete_cart(self, cart_id: str, *, context: SidecarContext) -> Mapping[str, Any]: ...

    def get_order(self, order_id: str) -> Mapping[str, Any]: ...

    def fulfill_order(self, order_id: str, fulfillment: Mapping[str, Any], *, context: SidecarContext) -> Mapping[str, Any]: ...

    def refund_order_payment(self, order_id: str, payment_collection_id: str, amount: float, *, context: SidecarContext, reason: str = "", note: str = "") -> Mapping[str, Any]: ...


class ProductResearchProvider(Protocol):
    def health(self) -> AdapterHealth: ...

    async def discover(self, query: str, *, context: SidecarContext) -> Sequence[Mapping[str, Any]]: ...


class SupplierProvider(Protocol):
    """Canonical supplier-offer boundary independent of commerce storage."""

    def health(self) -> AdapterHealth: ...

    def get_offers(self, product_ids: Sequence[str]) -> Sequence[Any]: ...


class BrowserWorkflowProvider(Protocol):
    def health(self) -> AdapterHealth: ...

    async def execute(self, workflow: str, payload: Mapping[str, Any], *, context: SidecarContext) -> Mapping[str, Any]: ...


class ContentPublisher(Protocol):
    def health(self) -> AdapterHealth: ...

    def publish(self, content: Mapping[str, Any], *, context: SidecarContext) -> Mapping[str, Any]: ...


class WorkflowAutomationProvider(Protocol):
    """Internal operational automation boundary (not a product runtime)."""

    def health(self) -> AdapterHealth: ...

    def trigger(self, workflow: str, payload: Mapping[str, Any], *, context: SidecarContext) -> Mapping[str, Any]: ...


class PaymentProvider(Protocol):
    """Fee-estimation and read-only payment/refund reconciliation boundary.

    Distinct from connectors.stripe_connector.get_revenue's ground-truth
    revenue job: no PaymentProvider implementation moves money directly or
    reconciles recognized revenue — it only estimates processing fees and
    reads payment/refund records for stack-cost planning."""

    def health(self) -> AdapterHealth: ...

    def estimate_fee(self, amount: float, *, currency: str = "MXN", payment_method: str = "card") -> Mapping[str, Any]: ...

    def list_payments(self, *, limit: int = 50, since: str | None = None) -> Sequence[Mapping[str, Any]]: ...

    def get_payment(self, payment_id: str) -> Mapping[str, Any]: ...

    def list_refunds(self, payment_id: str) -> Sequence[Mapping[str, Any]]: ...

    def handle_webhook(self, payload: Mapping[str, Any], *, context: SidecarContext) -> Mapping[str, Any]: ...


class CRMProvider(Protocol):
    """CRM pipeline boundary — contacts, opportunities, and activity, not a
    full customer-data-platform. No concrete adapter exists yet: the one
    catalog CRM candidate this Protocol was designed against (Twenty) is
    AGPL-3.0 and deferred pending legal review (see
    docs/oss/LICENSE_MANIFEST.yml) — GoHighLevel (proprietary) is the only
    CRM-capable provider with a live recommendation path today, via
    backend.stack_planner's existing automation recommendations."""

    def health(self) -> AdapterHealth: ...

    def upsert_contact(self, contact: Mapping[str, Any], *, context: SidecarContext) -> Mapping[str, Any]: ...

    def create_opportunity(self, opportunity: Mapping[str, Any], *, context: SidecarContext) -> Mapping[str, Any]: ...

    def update_stage(self, opportunity_id: str, stage: str, *, context: SidecarContext) -> Mapping[str, Any]: ...

    def record_activity(self, contact_id: str, activity: Mapping[str, Any], *, context: SidecarContext) -> Mapping[str, Any]: ...


class ConversationProvider(Protocol):
    """Inbox/support-conversation boundary — draft-and-record only; sending
    a message to a real customer is a `send_message_draft` result staged
    for human approval, never an autonomous send (see docs/LIVE_MODE_SAFETY.md's
    hand-off-to-human convention, matching services.sales_automation)."""

    def health(self) -> AdapterHealth: ...

    def create_contact(self, contact: Mapping[str, Any], *, context: SidecarContext) -> Mapping[str, Any]: ...

    def create_conversation(self, conversation: Mapping[str, Any], *, context: SidecarContext) -> Mapping[str, Any]: ...

    def send_message_draft(self, conversation_id: str, message: Mapping[str, Any], *, context: SidecarContext) -> Mapping[str, Any]: ...

    def record_inbound_message(self, conversation_id: str, message: Mapping[str, Any], *, context: SidecarContext) -> Mapping[str, Any]: ...

    def handoff_to_human(self, conversation_id: str, *, context: SidecarContext) -> Mapping[str, Any]: ...


class AnalyticsProvider(Protocol):
    """Backend/server-side product-analytics event capture and query
    boundary — distinct from the existing frontend-only posthog-js client
    (frontend/src/lib/posthog.ts), which talks to PostHog Cloud directly
    from the browser and is unaffected by this Protocol."""

    def health(self) -> AdapterHealth: ...

    def capture_event(self, event: Mapping[str, Any], *, context: SidecarContext) -> Mapping[str, Any]: ...

    def query_funnel(self, funnel: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def query_events(self, *, event_name: str, limit: int = 50, since: str | None = None) -> Sequence[Mapping[str, Any]]: ...


class MarketingAutomationProvider(Protocol):
    """Email/segment marketing-automation boundary — distinct from
    WorkflowAutomationProvider (n8n), which is scoped to MarketOS's own
    internal operational automation, not customer marketing campaigns."""

    def health(self) -> AdapterHealth: ...

    def upsert_contact(self, contact: Mapping[str, Any], *, context: SidecarContext) -> Mapping[str, Any]: ...

    def add_to_segment(self, contact_id: str, segment: str, *, context: SidecarContext) -> Mapping[str, Any]: ...

    def trigger_campaign(self, campaign_id: str, contact_id: str, *, context: SidecarContext) -> Mapping[str, Any]: ...

    def record_email_event(self, event: Mapping[str, Any], *, context: SidecarContext) -> Mapping[str, Any]: ...


class CustomerAutomationProvider(Protocol):
    """Customer-facing/product no-code workflow automation boundary (e.g.
    Activepieces) — distinct from WorkflowAutomationProvider (n8n), which is
    explicitly scoped to MarketOS's own internal operations, not a runtime a
    client's product could depend on."""

    def health(self) -> AdapterHealth: ...

    def trigger_workflow(self, workflow_id: str, payload: Mapping[str, Any], *, context: SidecarContext) -> Mapping[str, Any]: ...

    def get_workflow_status(self, run_id: str) -> Mapping[str, Any]: ...

    def list_available_workflows(self) -> Sequence[Mapping[str, Any]]: ...


class HostingProvider(Protocol):
    """Read-only hosting-plan/site-status boundary — MarketOS does not
    provision or de-provision hosting infrastructure itself; this Protocol
    exists for cost-plan comparison and basic status checks, not
    infrastructure management."""

    def health(self) -> AdapterHealth: ...

    def get_status(self) -> Mapping[str, Any]: ...

    def list_sites(self) -> Sequence[Mapping[str, Any]]: ...

    def get_plan_usage(self) -> Mapping[str, Any]: ...


class AgentProvider(Protocol):
    def health(self) -> AdapterHealth: ...

    def create(
        self,
        *,
        name: str,
        instructions: str,
        output_type: Any = None,
        tools: Sequence[Callable[..., Any]] = (),
    ) -> Any: ...
