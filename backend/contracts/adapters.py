"""Vendor-neutral contracts for MarketOS OSS adapters and sidecars."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol, Sequence


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


class AgentProvider(Protocol):
    def health(self) -> AdapterHealth: ...

    def create(self, *, name: str, instructions: str, output_type: Any = None) -> Any: ...
