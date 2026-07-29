"""API-only Postiz publisher boundary; no Postiz source is vendored."""
from __future__ import annotations

import os
import time
from typing import Any, Mapping

from backend.contracts.adapters import AdapterHealth, ContentPublisher, SidecarContext
from backend.integrations.webhook_dedup import WebhookEventLedger
from backend.commerce.contracts import CreativeBundle

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None


class PostizPublisherAdapter:
    name = "postiz"

    def __init__(self, base_url: str | None = None, *, token: str | None = None, client: Any = None):
        self.base_url = (base_url or os.getenv("POSTIZ_BASE_URL", "")).rstrip("/")
        self.token = token or os.getenv("POSTIZ_API_TOKEN", "")
        self.path = os.getenv("POSTIZ_PUBLISH_PATH", "/api/posts")
        self.max_retries = max(0, int(os.getenv("POSTIZ_MAX_RETRIES", "2")))
        self.retry_backoff_s = max(0.0, float(os.getenv("POSTIZ_RETRY_BACKOFF_S", "0.25")))
        self._client = client
        self.webhook_events = WebhookEventLedger(db_path=os.getenv("MARKETOS_WEBHOOK_DEDUP_DB", ":memory:"))

    def health(self) -> AdapterHealth:
        if not self.base_url or not self.token:
            return AdapterHealth(self.name, configured=False, reachable=False, detail="POSTIZ_BASE_URL or POSTIZ_API_TOKEN is unset")
        return AdapterHealth(self.name, configured=True, reachable=True, capabilities=("publish",))

    def accept_webhook(self, event_id: str) -> bool:
        return self.webhook_events.accept(self.name, event_id)

    def release_webhook(self, event_id: str) -> None:
        self.webhook_events.release(self.name, event_id)

    def publish_bundle(self, bundle: CreativeBundle, *, context: SidecarContext) -> Mapping[str, Any]:
        """Publish one canonical MarketOS creative artifact."""
        return self.publish({
            "content": bundle.primary_text or bundle.script,
            "headline": bundle.headline,
            "cta": bundle.cta,
            "platform": os.getenv("MARKETOS_DEFAULT_SOCIAL_PLATFORM", "instagram"),
            "artifact_id": bundle.artifact_id,
            "creative_id": bundle.creative_id,
            "product_id": bundle.product_id,
            "source_refs": list(bundle.source_refs),
        }, context=context)

    def publish(self, content: Mapping[str, Any], *, context: SidecarContext) -> Mapping[str, Any]:
        if context.dry_run:
            return {"id": f"dry-postiz-{context.idempotency_key or 'pending'}", "status": "planned", "dry_run": True, "content": dict(content)}
        if context.approval_state not in {"approved", "not_required"}:
            raise PermissionError("publishing requires approved MarketOS context")
        context.require_live_idempotency()
        if not self.base_url or not self.token:
            raise RuntimeError("Postiz is not configured")
        if httpx is None and self._client is None:
            raise RuntimeError("httpx is required for the Postiz adapter")
        headers = {"Authorization": f"Bearer {self.token}", **context.to_headers()}
        client = self._client or httpx.Client(timeout=15.0)
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = client.post(f"{self.base_url}{self.path}", json=dict(content), headers=headers)
                status_code = int(getattr(response, "status_code", 200) or 200)
                if status_code >= 500 and attempt < self.max_retries:
                    time.sleep(self.retry_backoff_s * (2 ** attempt))
                    continue
                response.raise_for_status()
                return response.json()
            except Exception as exc:
                last_error = exc
                status_code = int(getattr(locals().get("response"), "status_code", 0) or 0)
                retryable = status_code == 0 or status_code >= 500
                if not retryable or attempt >= self.max_retries:
                    raise
                time.sleep(self.retry_backoff_s * (2 ** attempt))
        raise RuntimeError("Postiz publish exhausted retries") from last_error


publisher: ContentPublisher = PostizPublisherAdapter()
