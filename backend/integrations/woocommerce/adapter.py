"""WooCommerce CommerceProvider adapter.

Implements the existing backend.contracts.adapters.CommerceProvider Protocol
(no new CommercePort) so callers depend on the same Protocol type as the
Medusa adapter. Structural differences from Medusa's Store-API cart model,
documented rather than papered over:

  * WooCommerce's REST API has no server-side cart resource. `create_cart`
    stages the order payload client-side only (a synthetic cart id, no HTTP
    call) — `complete_cart` is the one method that actually creates the
    order (`POST /orders`).
  * Core WooCommerce has no dedicated fulfillment sub-resource. `fulfill_order`
    is a best-effort mapping: an order status update plus a fulfillment note
    (`PUT /orders/{id}`), not a true fulfillment record.
  * `refund_order_payment` maps cleanly to `POST /orders/{id}/refunds`;
    `payment_collection_id` (a Medusa/CommerceProvider concept) is accepted
    for Protocol compatibility but not used — WooCommerce refunds are
    identified by order_id alone.

Same dry_run -> approval_state=="approved" -> require_live_idempotency()
gate sequence as backend.integrations.medusa.MedusaCommerceAdapter.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from backend.contracts.adapters import AdapterHealth, CommerceProvider, SidecarContext

from .client import WooCommerceClient


class WooCommerceCommerceAdapter:
    name = "woocommerce"

    def __init__(self, client: WooCommerceClient | None = None):
        self._client = client or WooCommerceClient()
        self._staged_carts: dict[str, dict[str, Any]] = {}

    def health(self) -> AdapterHealth:
        if not self._client.configured:
            return AdapterHealth(self.name, configured=False, reachable=False,
                                  detail="WOOCOMMERCE_STORE_URL/CONSUMER_KEY/CONSUMER_SECRET is unset")
        reachable = self._client.ping()
        return AdapterHealth(
            self.name, configured=True, reachable=reachable,
            capabilities=("catalog", "inventory", "orders", "refunds") if reachable else (),
            detail="" if reachable else "WooCommerce system_status probe failed",
        )

    @staticmethod
    def _require_approved_mutation(context: SidecarContext, operation: str) -> None:
        if context.approval_state != "approved":
            raise PermissionError(f"WooCommerce {operation} requires approved MarketOS context")
        context.require_live_idempotency()

    def list_products(self, *, limit: int = 50) -> Sequence[Mapping[str, Any]]:
        payload = self._client.request("GET", "/products", params={"per_page": max(1, min(limit, 100))})
        return payload.get("data", payload) if isinstance(payload.get("data"), list) else payload.get("products", [])

    def get_inventory(self, product_ids: Sequence[str]) -> Sequence[Mapping[str, Any]]:
        rows: list[Mapping[str, Any]] = []
        for product_id in product_ids:
            try:
                rows.append(self._client.request("GET", f"/products/{product_id}"))
            except Exception:
                continue
        return rows

    def create_order(self, order: Mapping[str, Any], *, context: SidecarContext) -> Mapping[str, Any]:
        if context.dry_run:
            return {"id": f"dry-woo-order-{context.idempotency_key or 'pending'}", "dry_run": True, "order": dict(order)}
        self._require_approved_mutation(context, "order creation")
        return self._client.request("POST", "/orders", json=dict(order))

    def create_cart(self, cart: Mapping[str, Any], *, context: SidecarContext) -> Mapping[str, Any]:
        """Client-side staging only — WooCommerce has no server-side cart
        resource, so this never calls the Woo API regardless of dry_run."""
        cart_id = f"woo-cart-{context.idempotency_key or context.run_id or 'pending'}"
        self._staged_carts[cart_id] = dict(cart)
        return {"id": cart_id, "dry_run": context.dry_run, "cart": dict(cart), "staged_locally": True}

    def complete_cart(self, cart_id: str, *, context: SidecarContext) -> Mapping[str, Any]:
        cart_id = str(cart_id).strip()
        if not cart_id:
            raise ValueError("cart_id is required")
        if context.dry_run:
            return {"id": f"dry-woo-order-{context.idempotency_key or cart_id}", "dry_run": True, "cart_id": cart_id}
        self._require_approved_mutation(context, "checkout")
        staged = self._staged_carts.pop(cart_id, {})
        return self._client.request("POST", "/orders", json=staged)

    def get_order(self, order_id: str) -> Mapping[str, Any]:
        return self._client.request("GET", f"/orders/{order_id}")

    def fulfill_order(self, order_id: str, fulfillment: Mapping[str, Any], *, context: SidecarContext) -> Mapping[str, Any]:
        """Best-effort mapping: WooCommerce core has no fulfillment
        sub-resource, so this updates order status + attaches fulfillment
        details as meta_data rather than creating a true fulfillment record."""
        if context.dry_run:
            return {
                "id": f"dry-woo-fulfillment-{context.idempotency_key or order_id}",
                "dry_run": True, "order_id": order_id, "fulfillment": dict(fulfillment),
            }
        self._require_approved_mutation(context, "fulfillment")
        body = {
            "status": fulfillment.get("status", "completed"),
            "meta_data": [{"key": "marketos_fulfillment", "value": dict(fulfillment)}],
        }
        return self._client.request("PUT", f"/orders/{order_id}", json=body)

    def refund_order_payment(
        self, order_id: str, payment_collection_id: str, amount: float, *,
        context: SidecarContext, reason: str = "", note: str = "",
    ) -> Mapping[str, Any]:
        if amount <= 0:
            raise ValueError("refund amount must be a positive value")
        if context.dry_run:
            return {
                "id": f"dry-woo-refund-{context.idempotency_key or order_id}",
                "dry_run": True, "order_id": order_id, "amount": amount,
            }
        self._require_approved_mutation(context, "refund")
        body: dict[str, Any] = {"amount": str(amount)}
        if reason:
            body["reason"] = reason
        return self._client.request("POST", f"/orders/{order_id}/refunds", json=body)


commerce_provider_woocommerce: CommerceProvider = WooCommerceCommerceAdapter()
