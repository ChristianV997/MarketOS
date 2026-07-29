"""HTTP adapter for an optional Medusa commerce sidecar.

MarketOS remains usable without Medusa. Live operations are opt-in and carry
the shared sidecar context so lineage and idempotency survive the boundary.
"""
from __future__ import annotations

import os
from typing import Any, Mapping, Sequence

from backend.contracts.adapters import AdapterHealth, CommerceProvider, SidecarContext

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None


class MedusaCommerceAdapter:
    name = "medusa"

    def __init__(self, base_url: str | None = None, *, timeout_s: float = 10.0, client: Any = None):
        self.base_url = (base_url or os.getenv("MEDUSA_BASE_URL", "")).rstrip("/")
        self.timeout_s = timeout_s
        self._client = client

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    def _request(self, method: str, path: str, *, context: SidecarContext | None = None, **kwargs: Any) -> dict[str, Any]:
        if not self.configured:
            raise RuntimeError("Medusa is not configured; set MEDUSA_BASE_URL")
        if httpx is None and self._client is None:
            raise RuntimeError("httpx is required for the Medusa adapter")
        headers = dict(kwargs.pop("headers", {}) or {})
        if context and context.idempotency_key:
            headers["Idempotency-Key"] = context.idempotency_key
        if context:
            headers.update({
                "X-MarketOS-Workspace": context.workspace_id,
                "X-MarketOS-Run": context.run_id,
                "X-MarketOS-Artifact": context.artifact_id,
            })
        client = self._client or httpx.Client(base_url=self.base_url, timeout=self.timeout_s)
        response = client.request(method, path, headers=headers, **kwargs)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {"data": payload}

    def health(self) -> AdapterHealth:
        if not self.configured:
            return AdapterHealth(self.name, configured=False, reachable=False, detail="MEDUSA_BASE_URL is unset")
        try:
            self._request("GET", "/health")
            return AdapterHealth(self.name, configured=True, reachable=True, capabilities=("catalog", "inventory", "orders"))
        except Exception as exc:
            return AdapterHealth(self.name, configured=True, reachable=False, detail=str(exc))

    def list_products(self, *, limit: int = 50) -> Sequence[Mapping[str, Any]]:
        payload = self._request("GET", "/store/products", params={"limit": max(1, min(limit, 100))})
        return payload.get("products", payload.get("data", []))

    def get_inventory(self, product_ids: Sequence[str]) -> Sequence[Mapping[str, Any]]:
        if not product_ids:
            return []
        payload = self._request("GET", "/admin/inventory-items", params={"product_id": list(product_ids)})
        return payload.get("inventory_items", payload.get("data", []))

    def create_order(self, order: Mapping[str, Any], *, context: SidecarContext) -> Mapping[str, Any]:
        if context.dry_run:
            return {"id": f"dry-medusa-order-{context.idempotency_key or 'pending'}", "dry_run": True, "order": dict(order)}
        if context.approval_state not in {"approved", "not_required"}:
            raise PermissionError("Medusa order requires approved MarketOS context")
        return self._request("POST", "/store/carts", context=context, json=dict(order))


commerce_provider: CommerceProvider = MedusaCommerceAdapter()
