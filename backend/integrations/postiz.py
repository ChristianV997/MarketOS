"""API-only Postiz publisher boundary; no Postiz source is vendored."""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.parse import urlparse

from backend.contracts.adapters import AdapterHealth, ContentPublisher, SidecarContext
from backend.integrations.webhook_dedup import WebhookEventLedger
from backend.commerce.contracts import CreativeBundle
from evaluation.contracts import CampaignObservation, DataQuality

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None


class PostizPublisherAdapter:
    name = "postiz"

    def __init__(self, base_url: str | None = None, *, token: str | None = None, integration_id: str | None = None, client: Any = None):
        self.base_url = (base_url or os.getenv("POSTIZ_BASE_URL", "")).rstrip("/")
        self.token = token or os.getenv("POSTIZ_API_TOKEN", "")
        self.integration_id = integration_id or os.getenv("POSTIZ_INTEGRATION_ID", "")
        self.path = os.getenv("POSTIZ_PUBLISH_PATH", "/posts")
        self.health_path = os.getenv("POSTIZ_HEALTH_PATH", "/integrations")
        self.auth_scheme = os.getenv("POSTIZ_AUTH_SCHEME", "").strip()
        self.allowed_hosts = frozenset(
            host.strip().lower().lstrip(".")
            for host in os.getenv("POSTIZ_ALLOWED_HOSTS", "api.postiz.com,postiz").split(",")
            if host.strip()
        )
        self.max_retries = max(0, int(os.getenv("POSTIZ_MAX_RETRIES", "2")))
        self.retry_backoff_s = max(0.0, float(os.getenv("POSTIZ_RETRY_BACKOFF_S", "0.25")))
        self._client = client
        self.webhook_events = WebhookEventLedger(db_path=os.getenv("MARKETOS_WEBHOOK_DEDUP_DB", ":memory:"))

    @staticmethod
    def _commercial_approval_granted() -> bool:
        """Keep AGPL-reviewed publishing disabled until an owner opts in."""
        return os.getenv("POSTIZ_COMMERCIAL_APPROVED", "false").strip().lower() in {"1", "true", "yes", "on"}

    def _base_url_error(self) -> str:
        parsed = urlparse(self.base_url)
        hostname = (parsed.hostname or "").lower()
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            return "POSTIZ_BASE_URL must be an http(s) URL without embedded credentials"
        if not self.allowed_hosts or not any(hostname == host or hostname.endswith("." + host) for host in self.allowed_hosts):
            return "POSTIZ_BASE_URL host is not allowlisted by POSTIZ_ALLOWED_HOSTS"
        return ""

    def health(self) -> AdapterHealth:
        if not self.base_url or not self.token:
            return AdapterHealth(self.name, configured=False, reachable=False, detail="POSTIZ_BASE_URL or POSTIZ_API_TOKEN is unset")
        error = self._base_url_error()
        if error:
            return AdapterHealth(self.name, configured=False, reachable=False, detail=error)
        if httpx is None and self._client is None:
            return AdapterHealth(self.name, configured=True, reachable=False, detail="httpx is required for Postiz health probes")
        client = self._client or httpx.Client(timeout=2.0)
        owns_client = self._client is None
        try:
            response = client.get(f"{self.base_url}{self.health_path}", headers=self._headers())
            reachable = bool(getattr(response, "is_success", int(getattr(response, "status_code", 500)) < 400))
            commercial = self._commercial_approval_granted()
            return AdapterHealth(
                self.name,
                configured=True,
                reachable=reachable,
                capabilities=("analytics", "publish") if reachable and commercial else (("analytics",) if reachable else ()),
                detail=(
                    "Postiz API reachable"
                    if commercial else "Postiz analytics reachable; live publishing disabled pending explicit AGPL commercial approval"
                ) if reachable else f"Postiz health endpoint returned {getattr(response, 'status_code', 'unknown')}",
            )
        except Exception as exc:
            return AdapterHealth(self.name, configured=True, reachable=False, detail=f"Postiz health probe failed: {exc}")
        finally:
            if owns_client:
                client.close()

    def accept_webhook(self, event_id: str) -> bool:
        return self.webhook_events.accept(self.name, event_id)

    def release_webhook(self, event_id: str) -> None:
        self.webhook_events.release(self.name, event_id)

    def _headers(self, context: SidecarContext | None = None) -> dict[str, str]:
        authorization = f"{self.auth_scheme} {self.token}".strip() if self.auth_scheme else self.token
        headers = {"Authorization": authorization}
        if context is not None:
            headers.update(context.to_headers())
        return headers

    @staticmethod
    def normalize_analytics(post_id: str, rows: Any) -> Mapping[str, Any]:
        """Normalize Postiz's provider-specific analytics labels conservatively."""
        totals: dict[str, int] = {}
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, Mapping):
                continue
            label = str(row.get("label") or "").strip().lower()
            points = row.get("data") if isinstance(row.get("data"), list) else []
            if not label or not points:
                continue
            latest = points[-1] if isinstance(points[-1], Mapping) else {}
            try:
                totals[label] = int(float(latest.get("total", 0) or 0))
            except (TypeError, ValueError):
                continue
        impressions = sum(value for label, value in totals.items() if label in {"impressions", "views", "reach"})
        clicks = sum(value for label, value in totals.items() if label in {"clicks", "link clicks"})
        engagements = sum(value for label, value in totals.items() if label in {"likes", "reactions", "comments", "shares", "reposts", "saves"})
        return {
            "post_id": post_id,
            "metrics": {
                "impressions": impressions,
                "clicks": clicks,
                "engagements": engagements,
                "engagement_rate": round(engagements / impressions, 6) if impressions else 0.0,
            },
            "labels": totals,
        }

    def fetch_post_analytics(self, post_id: str, *, days: int | None = None) -> Mapping[str, Any]:
        """Read one published Postiz post's engagement metrics."""
        post_id = str(post_id).strip()
        if not post_id:
            raise ValueError("post_id is required")
        if not self.base_url or not self.token:
            raise RuntimeError("Postiz is not configured")
        error = self._base_url_error()
        if error:
            raise PermissionError(error)
        if httpx is None and self._client is None:
            raise RuntimeError("httpx is required for the Postiz adapter")
        lookback_days = days if days is not None else int(os.getenv("POSTIZ_ANALYTICS_DAYS", "30"))
        if not 1 <= int(lookback_days) <= 365:
            raise ValueError("Postiz analytics days must be between 1 and 365")
        client = self._client or httpx.Client(timeout=15.0)
        owns_client = self._client is None
        try:
            response = client.get(
                f"{self.base_url}/analytics/post/{post_id}",
                params={"date": int(lookback_days)},
                headers=self._headers(),
            )
            response.raise_for_status()
            return self.normalize_analytics(post_id, response.json())
        finally:
            if owns_client:
                client.close()

    def fetch_campaign_observation(
        self,
        post_id: str,
        campaign_id: str,
        *,
        product_id: str = "",
        creative_id: str = "",
        days: int | None = None,
    ) -> CampaignObservation:
        """Convert read-only Postiz analytics into MarketOS feedback evidence."""
        campaign_id = str(campaign_id).strip()
        if not campaign_id:
            raise ValueError("campaign_id is required to reconcile Postiz analytics")
        analytics = self.fetch_post_analytics(post_id, days=days)
        metrics = analytics["metrics"]
        lookback_days = days if days is not None else int(os.getenv("POSTIZ_ANALYTICS_DAYS", "30"))
        return CampaignObservation(
            observation_id=f"postiz-analytics:{post_id}:{lookback_days}",
            campaign_id=campaign_id,
            product_id=str(product_id),
            creative_id=str(creative_id),
            impressions=int(metrics["impressions"]),
            clicks=int(metrics["clicks"]),
            quality=DataQuality(provenance="live", attribution="attributed", source_ref=f"postiz:{post_id}"),
            metadata={"source": "postiz", "post_id": post_id, "engagements": metrics["engagements"], "engagement_rate": metrics["engagement_rate"], "labels": analytics["labels"]},
        )

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

    def _payload(self, content: Mapping[str, Any]) -> Mapping[str, Any]:
        """Map canonical creative data to the Postiz public API payload."""
        if "posts" in content:
            return dict(content)
        integration_id = str(content.get("integration_id") or self.integration_id).strip()
        if not integration_id:
            raise ValueError("Postiz publishing requires POSTIZ_INTEGRATION_ID or content.integration_id")
        platform = str(content.get("platform") or "instagram")
        settings = dict(content.get("settings") or {})
        settings.setdefault("__type", platform)
        if platform in {"instagram", "instagram-standalone"}:
            settings.setdefault("post_type", "post")
        post_type = str(content.get("type") or os.getenv("POSTIZ_POST_TYPE", "draft"))
        if post_type not in {"draft", "schedule", "now"}:
            raise ValueError("Postiz post type must be draft, schedule, or now")
        date = str(content.get("date") or os.getenv("POSTIZ_PUBLISH_DATE", "") or datetime.now(timezone.utc).isoformat())
        return {
            "type": post_type,
            "date": date,
            "shortLink": bool(content.get("short_link", False)),
            "tags": list(content.get("tags") or []),
            "posts": [{
                "integration": {"id": integration_id},
                "value": [{"content": str(content.get("content") or content.get("text") or ""), "image": list(content.get("images") or [])}],
                "settings": settings,
            }],
        }

    def publish(self, content: Mapping[str, Any], *, context: SidecarContext) -> Mapping[str, Any]:
        if context.dry_run:
            return {"id": f"dry-postiz-{context.idempotency_key or 'pending'}", "status": "planned", "dry_run": True, "content": dict(content)}
        if context.approval_state != "approved":
            raise PermissionError("publishing requires approved MarketOS context")
        context.require_live_idempotency()
        if not self._commercial_approval_granted():
            raise PermissionError("Postiz live publishing is disabled pending explicit AGPL commercial approval")
        if not self.base_url or not self.token:
            raise RuntimeError("Postiz is not configured")
        error = self._base_url_error()
        if error:
            raise PermissionError(error)
        if httpx is None and self._client is None:
            raise RuntimeError("httpx is required for the Postiz adapter")
        headers = self._headers(context)
        client = self._client or httpx.Client(timeout=15.0)
        owns_client = self._client is None
        last_error: Exception | None = None
        try:
            for attempt in range(self.max_retries + 1):
                response = None
                try:
                    response = client.post(f"{self.base_url}{self.path}", json=self._payload(content), headers=headers)
                    status_code = int(getattr(response, "status_code", 200) or 200)
                    if status_code >= 500 and attempt < self.max_retries:
                        time.sleep(self.retry_backoff_s * (2 ** attempt))
                        continue
                    response.raise_for_status()
                    return response.json()
                except Exception as exc:
                    last_error = exc
                    status_code = int(getattr(response, "status_code", 0) or 0)
                    retryable = status_code == 0 or status_code >= 500
                    if not retryable or attempt >= self.max_retries:
                        raise
                    time.sleep(self.retry_backoff_s * (2 ** attempt))
            raise RuntimeError("Postiz publish exhausted retries") from last_error
        finally:
            if owns_client:
                client.close()


publisher: ContentPublisher = PostizPublisherAdapter()
