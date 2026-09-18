"""Dry-run Higgsfield creative adapter.

Optional SDK detection never imports credentials and never calls the network.
Live mode is a declared unavailable future path.
"""
from __future__ import annotations

import importlib.util
from typing import Any, Mapping

from .catalog import capability_catalog, locale_supported, lookup
from .contracts import (
    SCHEMA,
    CreativeJob,
    CreativeJobRequest,
    replay_hash,
)

PROVIDER = "higgsfield.catalog"
LIVE_PREREQUISITES = (
    "human_approval",
    "evidence_refs",
    "budget_or_credit_cap",
    "idempotency_key",
    "audit_event",
    "rollback_plan",
    "provider_terms_review",
    "privacy_review",
)


def detect_optional_sdk() -> dict[str, Any]:
    """Detect higgsfield_client without importing or reading env secrets."""
    spec = importlib.util.find_spec("higgsfield_client")
    return {
        "module": "higgsfield_client",
        "present": spec is not None,
        "imported": False,
        "credentials_read": False,
        "network_calls": False,
        "usable": False,
        "reason": "optional SDK is never imported in this adapter",
    }


def classify_error(kind: str) -> str:
    mapping = {
        "timeout": "timeout_classified",
        "unavailable": "provider_unavailable",
        "secret": "rejected_secret",
        "html": "rejected_secret",
        "missing": "missing_evidence",
        "locale": "unsupported",
        "live": "blocked",
    }
    return mapping.get(kind, "blocked")


class HiggsfieldCreativeAdapter:
    def plan(self, request: CreativeJobRequest, *, simulate: str | None = None) -> CreativeJob:
        if request.mode == "live_unavailable" or simulate == "live":
            return self._job(request, "blocked", "rejected", ("live mode is unavailable",), classify="live")
        if simulate == "timeout":
            evidence = request.mode if request.mode in {"fixture", "manual_import"} else "simulated"
            return self._job(request, "timeout_classified", evidence, ("provider timeout classified",), classify="timeout")
        if simulate == "unavailable":
            return self._job(request, "provider_unavailable", "unknown", ("provider unavailable",), classify="unavailable")
        if not locale_supported(request.locale):
            return self._job(request, "unsupported", "rejected", (f"unsupported locale: {request.locale}",), classify="locale")
        if not request.evidence_ids:
            return self._job(request, "missing_evidence", "missing", ("missing evidence ids",), classify="missing")
        cap = lookup(request.creative_type)
        if cap is None:
            return self._job(request, "unsupported", "rejected", ("unknown capability",))
        evidence_state = {
            "fixture": "fixture",
            "manual_import": "manual_import",
            "dry_run": "simulated",
            "blocked_live": "rejected",
        }.get(request.mode, "unknown")
        status = "blocked" if request.mode == "blocked_live" else "dry_run_complete"
        refs = (
            f"draft://{request.creative_type}/{request.product_id}",
            f"catalog://{cap.source_skill}",
        )
        return self._job(
            request,
            status,
            evidence_state,
            (),
            result_refs=refs,
            cost=cap.estimated_credits,
        )

    def _job(
        self,
        request: CreativeJobRequest,
        status: str,
        evidence_state: str,
        errors: tuple[str, ...],
        *,
        result_refs: tuple[str, ...] = (),
        cost: str | None = None,
        classify: str | None = None,
    ) -> CreativeJob:
        if classify and not errors:
            errors = (classify_error(classify),)
        payload = {
            "request_id": request.request_id,
            "workspace_id": request.workspace_id,
            "creative_type": request.creative_type,
            "mode": request.mode,
            "locale": request.locale,
            "evidence_ids": list(request.evidence_ids),
            "status": status,
        }
        return CreativeJob(
            schema=SCHEMA,
            job_id=f"job-{request.request_id}",
            request=request,
            provider=PROVIDER,
            status=status,
            evidence_state=evidence_state,
            result_refs=result_refs,
            cost_estimate_credits=cost or request.cost_estimate_credits,
            approval_required=LIVE_PREREQUISITES,
            live_attestation=False,
            replay=replay_hash(payload),
            errors=errors,
            client_safe=True,
        )


def plan_creative_job(request: CreativeJobRequest | Mapping[str, Any], **kwargs: Any) -> CreativeJob:
    if isinstance(request, Mapping):
        request = CreativeJobRequest(
            request_id=str(request["request_id"]),
            workspace_id=str(request["workspace_id"]),
            lane=str(request.get("lane", "internal")),
            offer_id=str(request.get("offer_id", "offer-unknown")),
            product_id=str(request.get("product_id", "product-unknown")),
            market_lane=str(request.get("market_lane", "US")),
            channel=str(request.get("channel", "marketplace")),
            creative_type=str(request["creative_type"]),
            mode=str(request.get("mode", "dry_run")),
            locale=str(request.get("locale", "en")),
            claims=tuple(request.get("claims", ())),
            evidence_ids=tuple(request.get("evidence_ids", ())),
            prompt_metadata=str(request.get("prompt_metadata", "")),
            reference_asset_ids=tuple(request.get("reference_asset_ids", ())),
        )
    return HiggsfieldCreativeAdapter().plan(request, **kwargs)


def attach_launch_draft_context(job: CreativeJob) -> dict[str, Any]:
    """Compose with existing launch-draft authority without mutating it."""
    from evaluation.commerce.launch_draft_pack import VERSION

    body = job.to_dict()
    body["launch_draft_authority"] = VERSION
    body["launch_authorized"] = False
    body["shopify_status"] = "draft"
    body["medusa_status"] = "draft"
    return body


def governance_gate(job: CreativeJob) -> dict[str, Any]:
    """Record TrustOS / Approval Ledger prerequisites; do not execute them."""
    return {
        "job_id": job.job_id,
        "approval_ledger_required": True,
        "trustos_export_required": True,
        "prerequisites": list(LIVE_PREREQUISITES),
        "live_allowed": False,
        "sdk": detect_optional_sdk(),
        "catalog": list(capability_catalog()),
    }


__all__ = [
    "PROVIDER",
    "LIVE_PREREQUISITES",
    "HiggsfieldCreativeAdapter",
    "plan_creative_job",
    "detect_optional_sdk",
    "attach_launch_draft_context",
    "governance_gate",
]
