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
        # Medusa prices and inventory are variant-scoped. Request calculated
        # prices explicitly instead of treating a product shell as sellable.
        payload = self._request(
            "GET",
            "/store/products",
            params={"limit": max(1, min(limit, 100)), "fields": "*variants.calculated_price"},
        )
        return payload.get("products", payload.get("data", []))

    @staticmethod
    def normalize_products(rows: Sequence[Mapping[str, Any]]) -> list[ProductCandidate]:
        result: list[ProductCandidate] = []
        for row in rows:
            product_id = str(row.get("id") or row.get("product_id") or "").strip()
            name = str(row.get("title") or row.get("name") or "").strip()
            if not product_id or not name:
                continue
            variants = row.get("variants")
            if not isinstance(variants, Sequence) or isinstance(variants, (str, bytes)) or not variants:
                variants = (row,)
            for variant in variants:
                if not isinstance(variant, Mapping):
                    continue
                variant_id = str(variant.get("id") or product_id).strip()
                if not variant_id:
                    continue
                calculated = variant.get("calculated_price")
                calculated = calculated if isinstance(calculated, Mapping) else {}
                variant_title = str(variant.get("title") or "").strip()
                candidate_name = name if not variant_title or variant_title.lower() == "default variant" else f"{name} — {variant_title}"
                try:
                    # Medusa V2 uses major currency units for price amounts.
                    price = float(variant.get("selling_price") or calculated.get("calculated_amount") or variant.get("price") or row.get("selling_price") or row.get("price") or 0.0)
                except (TypeError, ValueError):
                    price = 0.0
                result.append(ProductCandidate(
                    product_id=variant_id,
                    name=candidate_name,
                    currency=str(calculated.get("currency_code") or variant.get("currency_code") or row.get("currency_code") or row.get("currency") or "USD").upper(),
                    selling_price=max(0.0, price),
                    source_signal_ids=(f"medusa:{product_id}",),
                    quality=DataQuality(provenance="live", attribution="attributed", source_ref=f"medusa:{product_id}:{variant_id}"),
                ))
        return result

    def get_inventory(self, product_ids: Sequence[str]) -> Sequence[Mapping[str, Any]]:
        if not product_ids:
            return []
        # Inventory items link to product *variants* and location levels. The
        # Admin API does not make a product_id filter the canonical join; fetch
        # those links and filter locally by the candidate's variant ID.
        payload = self._request(
            "GET",
            "/admin/inventory-items",
            params={"limit": 100, "fields": "*variants,*location_levels"},
        )
        rows = payload.get("inventory_items", payload.get("data", []))
        requested = {str(product_id) for product_id in product_ids}
        matching: list[Mapping[str, Any]] = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            variants = row.get("variants")
            variant_ids = {
                str(variant.get("id") or "")
                for variant in variants
                if isinstance(variant, Mapping)
            } if isinstance(variants, Sequence) and not isinstance(variants, (str, bytes)) else set()
            fallback = str(row.get("variant_id") or row.get("product_id") or "")
            if requested.intersection(variant_ids) or fallback in requested:
                matching.append(row)
        return matching

    def get_offers(self, product_ids: Sequence[str]) -> Sequence[SupplierOffer]:
        """Expose inventory as canonical supplier offers for ranking."""
        return self.normalize_inventory(self.get_inventory(product_ids))

    @staticmethod
    def normalize_inventory(rows: Sequence[Mapping[str, Any]]) -> list[SupplierOffer]:
        offers: list[SupplierOffer] = []
        for row in rows:
            variants = row.get("variants")
            variant_ids = [
                str(variant.get("id") or "").strip()
                for variant in variants
                if isinstance(variant, Mapping) and str(variant.get("id") or "").strip()
            ] if isinstance(variants, Sequence) and not isinstance(variants, (str, bytes)) else []
            if not variant_ids:
                fallback = str(row.get("variant_id") or row.get("product_id") or "").strip()
                variant_ids = [fallback] if fallback else []
            levels = row.get("location_levels")
            if isinstance(levels, Sequence) and not isinstance(levels, (str, bytes)):
                available = 0
                valid_level = False
                for level in levels:
                    if not isinstance(level, Mapping):
                        continue
                    try:
                        available += max(0, int(level.get("stocked_quantity", 0) or 0) - int(level.get("reserved_quantity", 0) or 0))
                        valid_level = True
                    except (TypeError, ValueError):
                        continue
                inventory_units = available if valid_level else None
            else:
                inventory_units = int(row["stocked_quantity"]) if row.get("stocked_quantity") is not None else None
            for product_id in variant_ids:
                offers.append(SupplierOffer(
                    supplier_id=f"medusa:{row.get('id') or row.get('inventory_item_id') or product_id}:{product_id}", product_id=product_id,
                    unit_cost=float(row.get("unit_cost") or row.get("cost") or 0.0),
                    inventory_units=inventory_units,
                    currency=str(row.get("currency_code") or "USD").upper(),
                    quality=DataQuality(provenance="live", attribution="attributed", source_ref=f"medusa:{row.get('id') or product_id}"),
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

    @staticmethod
    def _cart_with_lineage(cart: Mapping[str, Any], context: SidecarContext) -> dict[str, Any]:
        """Persist sidecar lineage where Medusa order webhooks can return it."""
        body = dict(cart)
        raw_metadata = body.get("metadata") or {}
        if not isinstance(raw_metadata, Mapping):
            raise ValueError("Medusa cart metadata must be a mapping")
        metadata = dict(raw_metadata)
        lineage = {
            "marketos_workspace": context.workspace_id,
            "marketos_run_id": context.run_id,
            "marketos_artifact_id": context.artifact_id,
            "marketos_parent_ids": list(context.parent_ids),
        }
        for key, value in lineage.items():
            if value != "" and value != []:
                metadata.setdefault(key, value)
        body["metadata"] = metadata
        return body

    def create_cart(self, cart: Mapping[str, Any], *, context: SidecarContext) -> Mapping[str, Any]:
        body = self._cart_with_lineage(cart, context)
        if context.dry_run:
            return {"id": f"dry-medusa-cart-{context.idempotency_key or 'pending'}", "dry_run": True, "cart": body}
        self._require_approved_mutation(context, "cart creation")
        return self._request("POST", "/store/carts", context=context, json=body)

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
        amount: float,
        *,
        context: SidecarContext,
        reason: str = "",
        note: str = "",
    ) -> Mapping[str, Any]:
        """Refund a captured payment in Medusa major currency units after approval.

        Medusa ties a refund to a payment collection, rather than treating an
        order ID as sufficient authorization to move money.
        """
        order_id = self._resource_id(order_id, "order_id")
        payment_collection_id = self._resource_id(payment_collection_id, "payment_collection_id")
        if isinstance(amount, bool):
            raise ValueError("refund amount must be a positive major-currency value")
        try:
            amount_value = float(amount)
        except (TypeError, ValueError) as exc:
            raise ValueError("refund amount must be a positive major-currency value") from exc
        if amount_value <= 0:
            raise ValueError("refund amount must be a positive major-currency value")
        body = {"amount": amount_value}
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
