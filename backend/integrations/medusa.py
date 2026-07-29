"""HTTP adapter for an optional Medusa commerce sidecar.

MarketOS remains usable without Medusa. Live operations are opt-in and carry
the shared sidecar context so lineage and idempotency survive the boundary.
"""
from __future__ import annotations

import os
from typing import Any, Mapping, Sequence

from backend.contracts.adapters import AdapterHealth, CommerceProvider, SidecarContext, SupplierProvider
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
        if context:
            headers.update(context.to_headers())
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
                capabilities=("catalog", "inventory", "cart", "orders", "fulfillment", "refunds"),
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

    def get_offers(self, product_ids: Sequence[str]) -> Sequence[SupplierOffer]:
        """Expose inventory as canonical supplier offers for ranking."""
        return self.normalize_inventory(self.get_inventory(product_ids))

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
        self._require_approved_mutation(context, "cart creation")
        return self._request("POST", "/store/carts", context=context, json=dict(cart))

    def complete_cart(self, cart_id: str, *, context: SidecarContext) -> Mapping[str, Any]:
        cart_id = str(cart_id).strip()
        if not cart_id:
            raise ValueError("cart_id is required")
        if context.dry_run:
            return {"id": f"dry-medusa-order-{context.idempotency_key or cart_id}", "dry_run": True, "cart_id": cart_id}
        self._require_approved_mutation(context, "checkout")
        return self._request("POST", f"/store/carts/{cart_id}/complete", context=context, json={})

    @staticmethod
    def _resource_id(value: str, label: str) -> str:
        """Validate IDs before interpolating them into a Medusa route."""
        normalized = str(value or "").strip()
        if not normalized or "/" in normalized or "?" in normalized or "#" in normalized:
            raise ValueError(f"{label} is required and must be a single Medusa resource ID")
        return normalized

    @staticmethod
    def _require_approved_mutation(context: SidecarContext, operation: str) -> None:
        if context.approval_state != "approved":
            raise PermissionError(f"Medusa {operation} requires approved MarketOS context")
        context.require_live_idempotency()

    def get_order(self, order_id: str) -> Mapping[str, Any]:
        """Retrieve a canonical order without enabling any financial action."""
        order_id = self._resource_id(order_id, "order_id")
        return self._request("GET", f"/admin/orders/{order_id}")

    def fulfill_order(
        self,
        order_id: str,
        fulfillment: Mapping[str, Any],
        *,
        context: SidecarContext,
    ) -> Mapping[str, Any]:
        """Create an approved, retry-safe Medusa V2 order fulfillment.

        MarketOS intentionally does not infer quantities or stock locations. A
        caller must supply the reviewed Medusa item IDs and location ID.
        """
        order_id = self._resource_id(order_id, "order_id")
        body = dict(fulfillment)
        items = body.get("items")
        location_id = body.get("location_id")
        if not isinstance(items, Sequence) or isinstance(items, (str, bytes)) or not items:
            raise ValueError("fulfillment.items must be a non-empty sequence")
        if not str(location_id or "").strip():
            raise ValueError("fulfillment.location_id is required")
        if context.dry_run:
            return {
                "id": f"dry-medusa-fulfillment-{context.idempotency_key or order_id}",
                "dry_run": True,
                "order_id": order_id,
                "fulfillment": body,
            }
        self._require_approved_mutation(context, "fulfillment")
        return self._request("POST", f"/admin/orders/{order_id}/fulfillments", context=context, json=body)

    def refund_order_payment(
        self,
        order_id: str,
        payment_collection_id: str,
        amount: int,
        *,
        context: SidecarContext,
        reason: str = "",
        note: str = "",
    ) -> Mapping[str, Any]:
        """Refund a captured payment in minor currency units after approval.

        Medusa ties a refund to a payment collection, rather than treating an
        order ID as sufficient authorization to move money.
        """
        order_id = self._resource_id(order_id, "order_id")
        payment_collection_id = self._resource_id(payment_collection_id, "payment_collection_id")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise ValueError("refund amount must be a positive integer in minor currency units")
        body = {"amount": int(amount)}
        if reason:
            body["reason"] = str(reason)
        if note:
            body["note"] = str(note)
        if context.dry_run:
            return {
                "id": f"dry-medusa-refund-{context.idempotency_key or order_id}",
                "dry_run": True,
                "order_id": order_id,
                "payment_collection_id": payment_collection_id,
                "refund": body,
            }
        self._require_approved_mutation(context, "refund")
        return self._request(
            "POST",
            f"/admin/orders/{order_id}/payment-collections/{payment_collection_id}/refund",
            context=context,
            json=body,
        )


commerce_provider: CommerceProvider = MedusaCommerceAdapter()
supplier_provider: SupplierProvider = commerce_provider
