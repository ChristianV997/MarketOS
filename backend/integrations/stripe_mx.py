"""Stripe (Mexico) PaymentProvider adapter — fee estimation + read-only
payment/refund access.

Distinct from connectors.stripe_connector.get_revenue's ground-truth
revenue-reconciliation job: this adapter never reconciles recognized
revenue, it only estimates card-processing fees (always available, even
with zero credentials) and, when the optional `stripe` SDK and
STRIPE_SECRET_KEY are both present, reads payment/refund records. Reuses
the existing "stripe" credential key (backend.config._SERVICE_CREDENTIALS)
— no new credential key needed.
"""
from __future__ import annotations

import os
from typing import Any, Mapping, Sequence

from backend.contracts.adapters import AdapterHealth, PaymentProvider, SidecarContext
from backend.integrations.webhook_dedup import WebhookEventLedger

try:
    import stripe as _stripe_sdk
except ImportError:  # pragma: no cover
    _stripe_sdk = None

_FEE_PCT = float(os.getenv("PROVIDER_STRIPE_MX_FEE_PCT", "0.036"))
_FEE_FIXED_MXN = float(os.getenv("PROVIDER_STRIPE_MX_FEE_FIXED_MXN", "3.0"))


class StripeMxPaymentAdapter:
    name = "stripe_mx"

    def __init__(self) -> None:
        self.webhook_events = WebhookEventLedger(db_path=os.getenv("MARKETOS_WEBHOOK_DEDUP_DB", ":memory:"))

    @property
    def _secret_key(self) -> str:
        try:
            from backend.config import get_credential
            return get_credential("STRIPE_SECRET_KEY") or ""
        except Exception:
            return os.getenv("STRIPE_SECRET_KEY", "")

    @property
    def configured(self) -> bool:
        return bool(self._secret_key)

    def health(self) -> AdapterHealth:
        capabilities = ("fee_estimation",)
        if self.configured and _stripe_sdk is not None:
            capabilities = capabilities + ("payments", "refunds")
        return AdapterHealth(
            self.name, configured=self.configured, reachable=self.configured and _stripe_sdk is not None,
            capabilities=capabilities,
            detail="" if self.configured else "STRIPE_SECRET_KEY is unset (fee estimation still available)",
        )

    def estimate_fee(self, amount: float, *, currency: str = "MXN", payment_method: str = "card") -> Mapping[str, Any]:
        fee_amount = round(amount * _FEE_PCT + _FEE_FIXED_MXN, 2)
        return {
            "provider": self.name, "currency": currency, "payment_method": payment_method,
            "amount": round(amount, 2), "fee_pct": _FEE_PCT, "fee_fixed": _FEE_FIXED_MXN,
            "fee_amount": fee_amount, "net_amount": round(amount - fee_amount, 2),
        }

    def list_payments(self, *, limit: int = 50, since: str | None = None) -> Sequence[Mapping[str, Any]]:
        if not (self.configured and _stripe_sdk is not None):
            return [{"source": "unconfigured"}]
        _stripe_sdk.api_key = self._secret_key
        kwargs: dict[str, Any] = {"limit": max(1, min(limit, 100))}
        if since:
            kwargs["created"] = {"gte": since}
        return list(_stripe_sdk.PaymentIntent.list(**kwargs).auto_paging_iter())

    def get_payment(self, payment_id: str) -> Mapping[str, Any]:
        if not (self.configured and _stripe_sdk is not None):
            return {"source": "unconfigured", "payment_id": payment_id}
        _stripe_sdk.api_key = self._secret_key
        return _stripe_sdk.PaymentIntent.retrieve(payment_id)

    def list_refunds(self, payment_id: str) -> Sequence[Mapping[str, Any]]:
        if not (self.configured and _stripe_sdk is not None):
            return [{"source": "unconfigured", "payment_id": payment_id}]
        _stripe_sdk.api_key = self._secret_key
        return list(_stripe_sdk.Refund.list(payment_intent=payment_id).auto_paging_iter())

    def handle_webhook(self, payload: Mapping[str, Any], *, context: SidecarContext) -> Mapping[str, Any]:
        event_id = str(payload.get("id", ""))
        if context.dry_run:
            return {"dry_run": True, "event_id": event_id, "accepted": True}
        accepted = self.webhook_events.accept(self.name, event_id)
        return {"dry_run": False, "event_id": event_id, "accepted": accepted}


payment_provider_stripe_mx: PaymentProvider = StripeMxPaymentAdapter()
