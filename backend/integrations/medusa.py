"""HTTP adapter for an optional Medusa commerce sidecar.

MarketOS remains usable without Medusa. Live operations are opt-in and carry
the shared sidecar context so lineage and idempotency survive the boundary.
"""
from __future__ import annotations

import os
from typing import Any, Mapping, Sequence

from backend.contracts.adapters import AdapterHealth, CommerceProvider, SidecarContext
from evaluation.contracts import DataQuality, ProductCandidate, SupplierOffer
from backend.integrations.webhook_dedup import WebhookEventLedger

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None


class MedusaCommerceAdapter:
    name = "medusa"

    def __init__(self, base_url: str | None = None, *, token: str | None = None, timeout_s: float = 10.0, client: Any = None):
        self.base_url = (base_url or os.getenv("MEDUSA_BASE_URL", "")).rstrip("/")
        self.token = token or os.getenv("MEDUSA_API_TOKEN", "")
        self.timeout_s = timeout_s
        self._client = client
        self.webhook_events = WebhookEventLedger(db_path=os.getenv("MARKETOS_WEBHOOK_DEDUP_DB", ":memory:"))

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    def _request(self, method: str, path: str, *, context: SidecarContext | None = None, **kwargs: Any) -> dict[str, Any]:
        if not self.configured:
            raise RuntimeError("Medusa is not configured; set MEDUSA_BASE_URL")
        if httpx is None and self._client is None:
            raise RuntimeError("httpx is required for the Medusa adapter")
        headers = dict(kwargs.pop("headers", {}) or {})
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if context and context.idempotency_key:
            headers["Idempotency-Key"] = context.idempotency_key
        if context:
            headers.update({
                "X-MarketOS-Workspace": context.workspace_id,
                "X-MarketOS-Run": context.run_id,
                "X-MarketOS-Artifact": context.artifact_id,
                "X-MarketOS-Parents": ",".join(context.parent_ids),
                "X-MarketOS-Approval": context.approval_state,
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
            return AdapterHealth(
                self.name,
                configured=True,
                reachable=True,
                capabilities=("catalog", "inventory", "cart", "orders", "fulfillment"),
            )
        except Exception as exc:
            return AdapterHealth(self.name, configured=True, reachable=False, detail=str(exc))

    def accept_webhook(self, event_id: str) -> bool:
        return self.webhook_events.accept(self.name, event_id)

    def release_webhook(self, event_id: str) -> None:
        self.webhook_events.release(self.name, event_id)

    def list_products(self, *, limit: int = 50) -> Sequence[Mapping[str, Any]]:
        payload = self._request("GET", "/store/products", params={"limit": max(1, min(limit, 100))})
        return payload.get("products", payload.get("data", []))

    @staticmethod
    def normalize_products(rows: Sequence[Mapping[str, Any]]) -> list[ProductCandidate]:
        result: list[ProductCandidate] = []
        for row in rows:
            product_id = str(row.get("id") or row.get("product_id") or "").strip()
            name = str(row.get("title") or row.get("name") or "").strip()
            if not product_id or not name:
                continue
            result.append(ProductCandidate(
                product_id=product_id, name=name,
                currency=str(row.get("currency_code") or row.get("currency") or "USD").upper(),
                selling_price=float(row.get("selling_price") or row.get("price") or 0.0),
                quality=DataQuality(provenance="live", attribution="attributed", source_ref=f"medusa:{product_id}"),
            ))
        return result

    def get_inventory(self, product_ids: Sequence[str]) -> Sequence[Mapping[str, Any]]:
        if not product_ids:
            return []
        payload = self._request("GET", "/admin/inventory-items", params={"product_id": list(product_ids)})
        return payload.get("inventory_items", payload.get("data", []))

    @staticmethod
    def normalize_inventory(rows: Sequence[Mapping[str, Any]]) -> list[SupplierOffer]:
        offers: list[SupplierOffer] = []
        for row in rows:
            product_id = str(row.get("product_id") or row.get("variant_id") or "").strip()
            if not product_id:
                continue
            offers.append(SupplierOffer(
                supplier_id=f"medusa:{row.get('inventory_item_id') or product_id}", product_id=product_id,
                unit_cost=float(row.get("unit_cost") or row.get("cost") or 0.0),
                inventory_units=int(row["stocked_quantity"]) if row.get("stocked_quantity") is not None else None,
                currency=str(row.get("currency_code") or "USD").upper(),
                quality=DataQuality(provenance="live", attribution="attributed", source_ref=f"medusa:{product_id}"),
            ))
        return offers

    def create_order(self, order: Mapping[str, Any], *, context: SidecarContext) -> Mapping[str, Any]:
        """Compatibility entry point for creating a Medusa cart.

        Medusa's Store API creates an order by completing a cart; callers that
        need actual checkout should use ``complete_cart`` after ``create_cart``.
        Keeping this method preserves the existing CommerceProvider surface
        while removing the false implication that ``POST /store/carts`` is an
        order-creation endpoint.
        """
        return self.create_cart(order, context=context)

    def create_cart(self, cart: Mapping[str, Any], *, context: SidecarContext) -> Mapping[str, Any]:
        if context.dry_run:
            return {"id": f"dry-medusa-cart-{context.idempotency_key or 'pending'}", "dry_run": True, "cart": dict(cart)}
        if context.approval_state not in {"approved", "not_required"}:
            raise PermissionError("Medusa cart creation requires approved MarketOS context")
        return self._request("POST", "/store/carts", context=context, json=dict(cart))

    def complete_cart(self, cart_id: str, *, context: SidecarContext) -> Mapping[str, Any]:
        cart_id = str(cart_id).strip()
        if not cart_id:
            raise ValueError("cart_id is required")
        if context.dry_run:
            return {"id": f"dry-medusa-order-{context.idempotency_key or cart_id}", "dry_run": True, "cart_id": cart_id}
        if context.approval_state not in {"approved", "not_required"}:
            raise PermissionError("Medusa checkout requires approved MarketOS context")
        return self._request("POST", f"/store/carts/{cart_id}/complete", context=context, json={})


commerce_provider: CommerceProvider = MedusaCommerceAdapter()
