"""Normalized creative-job contract for MarketOS draft workflows.

This is the smallest port that does not exist on main. It is not a second
CompanyOS provider registry and does not authorize live generation.
"""
from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from typing import Any, Mapping

SCHEMA = "MarketOS.CreativeJob.v1"
MODES = frozenset({"fixture", "manual_import", "dry_run", "blocked_live", "live_unavailable"})
STATUSES = frozenset({
    "planned",
    "blocked",
    "missing_evidence",
    "unsupported",
    "rejected_secret",
    "timeout_classified",
    "provider_unavailable",
    "dry_run_complete",
})
CREATIVE_TYPES = frozenset({
    "product_photo",
    "marketplace_card",
    "ugc_video",
    "explainer_video",
    "brand_kit",
    "virality_metadata",
})
LANES = frozenset({"internal", "client"})
EVIDENCE_STATES = frozenset({
    "unknown",
    "missing",
    "assumed",
    "fixture",
    "manual_import",
    "simulated",
    "observed",
    "rejected",
    "stale",
})
SECRET_MARKERS = (
    "api_key",
    "hf_key",
    "hf_api_key",
    "hf_api_secret",
    "password",
    "token",
    "authorization",
    "bearer",
    "secret",
    "credential",
)
HTML_MARKERS = ("<html", "<script", "javascript:", "onerror=")
LIVE_MARKERS = (
    "place_order",
    "capture_payment",
    "launch_ad",
    "publish_listing",
    "deploy_website",
    "send_message",
)
SUPPORTED_MODELS = frozenset({"higgsfield.catalog.static"})


class CreativeAdapterError(ValueError):
    """Fail-closed adapter validation error."""


def _text(value: Any, field: str, *, allow_empty: bool = False, limit: int = 240) -> str:
    if not isinstance(value, str):
        raise CreativeAdapterError(f"invalid {field}")
    if any(unicodedata.category(char) == "Cc" for char in value):
        raise CreativeAdapterError(f"invalid {field}")
    cleaned = " ".join(value.split()).strip()
    if not cleaned and not allow_empty:
        raise CreativeAdapterError(f"invalid {field}")
    return cleaned[:limit]


def canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def replay_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CreativeJobRequest:
    request_id: str
    workspace_id: str
    lane: str
    offer_id: str
    product_id: str
    market_lane: str
    channel: str
    creative_type: str
    mode: str
    locale: str
    claims: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    prompt_metadata: str
    reference_asset_ids: tuple[str, ...]
    model_id: str = "higgsfield.catalog.static"
    cost_estimate_credits: str = "unknown"
    approval_state: str = "not_requested"
    generated_at: str = "2026-09-17T00:00:00Z"
    expires_at: str = "2026-10-17T00:00:00Z"
    sku_variant: str = ""
    supplier_offer_id: str = ""
    client_workspace_id: str = ""
    language: str = ""
    content_angle: str = ""
    prohibited_claims: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    business_model: str = "retail_margin"
    evidence_freshness: str = "current"
    source_governance_ref: str = "MarketOS.SourceGovernance.Higgsfield.v1-pending"

    def __post_init__(self) -> None:
        _text(self.request_id, "request_id")
        _text(self.workspace_id, "workspace_id")
        if ".." in self.workspace_id or "/" in self.workspace_id or "\\" in self.workspace_id:
            raise CreativeAdapterError("path traversal rejected")
        if self.lane not in LANES:
            raise CreativeAdapterError("invalid lane")
        _text(self.offer_id, "offer_id")
        _text(self.product_id, "product_id")
        _text(self.market_lane, "market_lane")
        _text(self.channel, "channel")
        if self.creative_type not in CREATIVE_TYPES:
            raise CreativeAdapterError("unsupported creative type")
        if self.mode not in MODES:
            raise CreativeAdapterError("invalid mode")
        _text(self.locale, "locale", limit=16)
        if not isinstance(self.claims, tuple) or not isinstance(self.evidence_ids, tuple):
            raise CreativeAdapterError("invalid evidence")
        _text(self.prompt_metadata, "prompt_metadata", allow_empty=True, limit=400)
        if self.model_id not in SUPPORTED_MODELS:
            raise CreativeAdapterError("unsupported model")
        if self.evidence_freshness not in {"current", "stale"}:
            raise CreativeAdapterError("invalid evidence freshness")
        blob = " ".join((self.prompt_metadata, *self.claims, self.request_id, self.content_angle)).lower()
        if any(marker in blob for marker in SECRET_MARKERS):
            raise CreativeAdapterError("secret-shaped request rejected")
        if any(marker in blob for marker in HTML_MARKERS):
            raise CreativeAdapterError("raw html retrieval rejected")
        if any(marker in blob for marker in LIVE_MARKERS):
            raise CreativeAdapterError("live action language rejected")


@dataclass(frozen=True)
class CreativeJob:
    schema: str
    job_id: str
    request: CreativeJobRequest
    provider: str
    status: str
    evidence_state: str
    result_refs: tuple[str, ...]
    cost_estimate_credits: str
    approval_required: tuple[str, ...]
    live_attestation: bool
    replay: str
    errors: tuple[str, ...]
    client_safe: bool
    record_kind: str = "planning_record"

    def __post_init__(self) -> None:
        if self.schema != SCHEMA:
            raise CreativeAdapterError("invalid schema")
        if self.status not in STATUSES:
            raise CreativeAdapterError("invalid status")
        if self.evidence_state not in EVIDENCE_STATES:
            raise CreativeAdapterError("invalid evidence state")
        if self.live_attestation:
            raise CreativeAdapterError("live attestation is unavailable")
        if self.request.mode in {"fixture", "manual_import", "dry_run", "blocked_live"} and self.evidence_state in {"observed"}:
            raise CreativeAdapterError("draft modes cannot become observed live evidence")

    def to_dict(self) -> dict[str, Any]:
        req = self.request
        return {
            "schema": self.schema,
            "job_id": self.job_id,
            "request_id": req.request_id,
            "workspace_id": req.workspace_id,
            "lane": req.lane,
            "offer_id": req.offer_id,
            "product_id": req.product_id,
            "sku_variant": req.sku_variant,
            "supplier_offer_id": req.supplier_offer_id or req.offer_id,
            "client_workspace_id": req.client_workspace_id or req.workspace_id,
            "market_lane": req.market_lane,
            "business_model": req.business_model,
            "channel": req.channel,
            "creative_type": req.creative_type,
            "mode": req.mode,
            "locale": req.locale,
            "language": req.language or req.locale,
            "content_angle": req.content_angle,
            "claims": list(req.claims),
            "prohibited_claims": list(req.prohibited_claims),
            "assumptions": list(req.assumptions),
            "missing_evidence": list(req.missing_evidence),
            "evidence_ids": list(req.evidence_ids),
            "evidence_freshness": req.evidence_freshness,
            "prompt_metadata": req.prompt_metadata,
            "reference_asset_ids": list(req.reference_asset_ids),
            "model_id": req.model_id,
            "provider": self.provider,
            "status": self.status,
            "evidence_state": self.evidence_state,
            "result_refs": list(self.result_refs),
            "cost_estimate_credits": self.cost_estimate_credits,
            "approval_state": req.approval_state,
            "approval_required": list(self.approval_required),
            "generated_at": req.generated_at,
            "expires_at": req.expires_at,
            "replay_hash": self.replay,
            "source_governance_ref": req.source_governance_ref,
            "live_attestation": False,
            "live_actions_taken": False,
            "published": False,
            "generated": False,
            "errors": list(self.errors),
            "client_safe": self.client_safe,
            "record_kind": self.record_kind,
            "confidence": "planning_only",
            "creative_quality": "draft_only",
            "commercial_validation": "not_commercially_validated",
        }

    def client_projection(self) -> dict[str, Any]:
        body = self.to_dict()
        body.pop("prompt_metadata", None)
        body["schema"] = "MarketOS.ClientCreativeProjection.v1"
        return body
