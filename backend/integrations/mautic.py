"""Mautic MarketingAutomationProvider adapter.

Implements the new backend.contracts.adapters.MarketingAutomationProvider
Protocol. Dry-run by default. `record_email_event` records an inbound
webhook-shaped email event (open/click/bounce) via the existing
WebhookEventLedger dedup mechanism — Mautic has no "push an email event"
API in the outbound direction, so this is a receive/dedup operation, not a
Mautic API call, mirroring how backend.integrations.stripe_mx.handle_webhook
handles inbound events.
"""
from __future__ import annotations

import os
from typing import Any, Mapping

from backend.contracts.adapters import AdapterHealth, MarketingAutomationProvider, SidecarContext
from backend.integrations.webhook_dedup import WebhookEventLedger

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None


class MauticMarketingAutomationAdapter:
    name = "mautic"

    def __init__(self, base_url: str | None = None, *, username: str | None = None,
                 password: str | None = None, timeout_s: float = 10.0, client: Any = None):
        self.base_url = (base_url or os.getenv("MAUTIC_BASE_URL", "")).rstrip("/")
        self.username = username or os.getenv("MAUTIC_USERNAME", "")
        self.password = password or os.getenv("MAUTIC_PASSWORD", "")
        self.timeout_s = timeout_s
        self._client = client
        self.webhook_events = WebhookEventLedger(db_path=os.getenv("MARKETOS_WEBHOOK_DEDUP_DB", ":memory:"))

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.username and self.password)

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if not self.configured:
            raise RuntimeError("Mautic is not configured; set MAUTIC_BASE_URL/USERNAME/PASSWORD")
        if httpx is None and self._client is None:
            raise RuntimeError("httpx is required for the Mautic adapter")
        client = self._client or httpx.Client(base_url=f"{self.base_url}/api", timeout=self.timeout_s, auth=(self.username, self.password))
        response = client.request(method, path, **kwargs)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {"data": payload}

    def health(self) -> AdapterHealth:
        if not self.configured:
            return AdapterHealth(self.name, configured=False, reachable=False,
                                  detail="MAUTIC_BASE_URL/USERNAME/PASSWORD is unset")
        try:
            self._request("GET", "/contacts", params={"limit": 1})
            return AdapterHealth(self.name, configured=True, reachable=True,
                                  capabilities=("email_marketing", "marketing_automation", "segmentation"))
        except Exception as exc:
            return AdapterHealth(self.name, configured=True, reachable=False, detail=str(exc))

    @staticmethod
    def _require_approved_mutation(context: SidecarContext, operation: str) -> None:
        if context.approval_state != "approved":
            raise PermissionError(f"Mautic {operation} requires approved MarketOS context")
        context.require_live_idempotency()

    def upsert_contact(self, contact: Mapping[str, Any], *, context: SidecarContext) -> Mapping[str, Any]:
        if context.dry_run:
            return {"id": f"dry-mautic-contact-{context.idempotency_key or 'pending'}", "dry_run": True, "contact": dict(contact)}
        self._require_approved_mutation(context, "contact upsert")
        return self._request("POST", "/contacts/new", json=dict(contact))

    def add_to_segment(self, contact_id: str, segment: str, *, context: SidecarContext) -> Mapping[str, Any]:
        if context.dry_run:
            return {"dry_run": True, "contact_id": contact_id, "segment": segment}
        self._require_approved_mutation(context, "segment membership")
        return self._request("POST", f"/segments/{segment}/contact/{contact_id}/add", json={})

    def trigger_campaign(self, campaign_id: str, contact_id: str, *, context: SidecarContext) -> Mapping[str, Any]:
        if context.dry_run:
            return {"dry_run": True, "campaign_id": campaign_id, "contact_id": contact_id}
        self._require_approved_mutation(context, "campaign trigger")
        return self._request("POST", f"/campaigns/{campaign_id}/contact/{contact_id}/add", json={})

    def record_email_event(self, event: Mapping[str, Any], *, context: SidecarContext) -> Mapping[str, Any]:
        event_id = str(event.get("id", ""))
        if context.dry_run:
            return {"dry_run": True, "event_id": event_id, "accepted": True}
        accepted = self.webhook_events.accept(self.name, event_id)
        return {"dry_run": False, "event_id": event_id, "accepted": accepted}


marketing_automation_provider_mautic: MarketingAutomationProvider = MauticMarketingAutomationAdapter()
