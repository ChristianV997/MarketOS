"""Chatwoot ConversationProvider adapter.

Implements the new backend.contracts.adapters.ConversationProvider Protocol.
Dry-run by default; `send_message_draft` never auto-sends to a real
customer — it stages a draft for human approval (see
docs/LIVE_MODE_SAFETY.md's hand-off-to-human convention), matching this
Protocol's own docstring.
"""
from __future__ import annotations

import os
from typing import Any, Mapping

from backend.contracts.adapters import AdapterHealth, ConversationProvider, SidecarContext

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None


class ChatwootConversationAdapter:
    name = "chatwoot"

    def __init__(self, base_url: str | None = None, *, api_access_token: str | None = None,
                 account_id: str | None = None, timeout_s: float = 10.0, client: Any = None):
        self.base_url = (base_url or os.getenv("CHATWOOT_BASE_URL", "")).rstrip("/")
        self.api_access_token = api_access_token or os.getenv("CHATWOOT_API_ACCESS_TOKEN", "")
        self.account_id = account_id or os.getenv("CHATWOOT_ACCOUNT_ID", "")
        self.timeout_s = timeout_s
        self._client = client

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_access_token and self.account_id)

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if not self.configured:
            raise RuntimeError("Chatwoot is not configured; set CHATWOOT_BASE_URL/API_ACCESS_TOKEN/ACCOUNT_ID")
        if httpx is None and self._client is None:
            raise RuntimeError("httpx is required for the Chatwoot adapter")
        headers = dict(kwargs.pop("headers", {}) or {})
        headers["api_access_token"] = self.api_access_token
        client = self._client or httpx.Client(base_url=f"{self.base_url}/api/v1/accounts/{self.account_id}", timeout=self.timeout_s)
        response = client.request(method, path, headers=headers, **kwargs)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {"data": payload}

    def health(self) -> AdapterHealth:
        if not self.configured:
            return AdapterHealth(self.name, configured=False, reachable=False,
                                  detail="CHATWOOT_BASE_URL/API_ACCESS_TOKEN/ACCOUNT_ID is unset")
        try:
            self._request("GET", "/inboxes")
            return AdapterHealth(self.name, configured=True, reachable=True,
                                  capabilities=("conversation_inbox", "support_ticketing"))
        except Exception as exc:
            return AdapterHealth(self.name, configured=True, reachable=False, detail=str(exc))

    @staticmethod
    def _require_approved_mutation(context: SidecarContext, operation: str) -> None:
        if context.approval_state != "approved":
            raise PermissionError(f"Chatwoot {operation} requires approved MarketOS context")
        context.require_live_idempotency()

    def create_contact(self, contact: Mapping[str, Any], *, context: SidecarContext) -> Mapping[str, Any]:
        if context.dry_run:
            return {"id": f"dry-chatwoot-contact-{context.idempotency_key or 'pending'}", "dry_run": True, "contact": dict(contact)}
        self._require_approved_mutation(context, "contact creation")
        return self._request("POST", "/contacts", json=dict(contact))

    def create_conversation(self, conversation: Mapping[str, Any], *, context: SidecarContext) -> Mapping[str, Any]:
        if context.dry_run:
            return {"id": f"dry-chatwoot-conversation-{context.idempotency_key or 'pending'}", "dry_run": True, "conversation": dict(conversation)}
        self._require_approved_mutation(context, "conversation creation")
        return self._request("POST", "/conversations", json=dict(conversation))

    def send_message_draft(self, conversation_id: str, message: Mapping[str, Any], *, context: SidecarContext) -> Mapping[str, Any]:
        """Always a draft — this never marks a message as sent to the real
        customer; that requires a separate, explicitly human-approved step
        outside this adapter (see docstring)."""
        return {
            "id": f"draft-chatwoot-message-{context.idempotency_key or conversation_id}",
            "conversation_id": conversation_id, "message": dict(message),
            "status": "draft_pending_human_approval",
        }

    def record_inbound_message(self, conversation_id: str, message: Mapping[str, Any], *, context: SidecarContext) -> Mapping[str, Any]:
        if context.dry_run:
            return {"dry_run": True, "conversation_id": conversation_id, "message": dict(message)}
        self._require_approved_mutation(context, "inbound message recording")
        return self._request("POST", f"/conversations/{conversation_id}/messages", json=dict(message))

    def handoff_to_human(self, conversation_id: str, *, context: SidecarContext) -> Mapping[str, Any]:
        if context.dry_run:
            return {"dry_run": True, "conversation_id": conversation_id, "status": "handed_off"}
        self._require_approved_mutation(context, "conversation handoff")
        return self._request("POST", f"/conversations/{conversation_id}/toggle_status", json={"status": "open"})


conversation_provider_chatwoot: ConversationProvider = ChatwootConversationAdapter()
