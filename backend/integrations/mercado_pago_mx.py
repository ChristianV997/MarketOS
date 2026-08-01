"""Mercado Pago (Mexico) PaymentProvider adapter — fee estimation + read-only
payment/refund access.

Fee estimation is always available even with zero credentials. When the
optional `mercadopago` SDK and MERCADOPAGO_ACCESS_TOKEN are both present,
reads payment/refund records. Uses the "mercadopago_mx" credential key
(backend.config._SERVICE_CREDENTIALS / backend.workspaces.credential_scope).
"""
from __future__ import annotations

import os
from typing import Any, Mapping, Sequence

from backend.contracts.adapters import AdapterHealth, PaymentProvider, SidecarContext
from backend.integrations.webhook_dedup import WebhookEventLedger

try:
    import mercadopago as _mp_sdk
except ImportError:  # pragma: no cover
    _mp_sdk = None

_FEE_PCT = float(os.getenv("PROVIDER_MERCADOPAGO_MX_FEE_PCT", "0.0349"))
_FEE_FIXED_MXN = float(os.getenv("PROVIDER_MERCADOPAGO_MX_FEE_FIXED_MXN", "0.0"))


class MercadoPagoMxPaymentAdapter:
    name = "mercado_pago_mx"

    def __init__(self) -> None:
        self.webhook_events = WebhookEventLedger(db_path=os.getenv("MARKETOS_WEBHOOK_DEDUP_DB", ":memory:"))

    @property
    def _access_token(self) -> str:
        try:
            from backend.config import get_credential
            return get_credential("MERCADOPAGO_ACCESS_TOKEN") or ""
        except Exception:
            return os.getenv("MERCADOPAGO_ACCESS_TOKEN", "")

    @property
    def configured(self) -> bool:
        return bool(self._access_token)

    def health(self) -> AdapterHealth:
        capabilities = ("fee_estimation",)
        if self.configured and _mp_sdk is not None:
            capabilities = capabilities + ("payments", "refunds")
        return AdapterHealth(
            self.name, configured=self.configured, reachable=self.configured and _mp_sdk is not None,
            capabilities=capabilities,
            detail="" if self.configured else "MERCADOPAGO_ACCESS_TOKEN is unset (fee estimation still available)",
        )

    def estimate_fee(self, amount: float, *, currency: str = "MXN", payment_method: str = "card") -> Mapping[str, Any]:
        fee_amount = round(amount * _FEE_PCT + _FEE_FIXED_MXN, 2)
        return {
            "provider": self.name, "currency": currency, "payment_method": payment_method,
            "amount": round(amount, 2), "fee_pct": _FEE_PCT, "fee_fixed": _FEE_FIXED_MXN,
            "fee_amount": fee_amount, "net_amount": round(amount - fee_amount, 2),
        }

    def _sdk(self):
        return _mp_sdk.SDK(self._access_token)

    def list_payments(self, *, limit: int = 50, since: str | None = None) -> Sequence[Mapping[str, Any]]:
        if not (self.configured and _mp_sdk is not None):
            return [{"source": "unconfigured"}]
        filters: dict[str, Any] = {"limit": max(1, min(limit, 100))}
        if since:
            filters["begin_date"] = since
        response = self._sdk().payment().search(filters)
        return response.get("response", {}).get("results", [])

    def get_payment(self, payment_id: str) -> Mapping[str, Any]:
        if not (self.configured and _mp_sdk is not None):
            return {"source": "unconfigured", "payment_id": payment_id}
        return self._sdk().payment().get(payment_id).get("response", {})

    def list_refunds(self, payment_id: str) -> Sequence[Mapping[str, Any]]:
        if not (self.configured and _mp_sdk is not None):
            return [{"source": "unconfigured", "payment_id": payment_id}]
        return self._sdk().refund().list(payment_id).get("response", [])

    def handle_webhook(self, payload: Mapping[str, Any], *, context: SidecarContext) -> Mapping[str, Any]:
        event_id = str(payload.get("id", ""))
        if context.dry_run:
            return {"dry_run": True, "event_id": event_id, "accepted": True}
        accepted = self.webhook_events.accept(self.name, event_id)
        return {"dry_run": False, "event_id": event_id, "accepted": accepted}


payment_provider_mercado_pago_mx: PaymentProvider = MercadoPagoMxPaymentAdapter()
