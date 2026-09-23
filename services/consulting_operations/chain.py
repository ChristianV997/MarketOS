"""Consulting Chain Readiness.

Implements the consulting pipeline chain evaluation:
offers -> engagement -> economics -> portfolio -> evidence register -> delivery.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

from .schemas import ConsultingEngagement
from .packager import package_deliverable
from evaluation.trustos.client_workspace_isolation import check_workspace_leakage


class ConsultingChainError(ValueError):
    """Failure inside the consulting chain."""


# Structural subtyping (Protocol) to avoid importing the actual catalog
class OfferCatalogItem(Protocol):
    type: str
    id: str


@dataclass
class ChainResult:
    status: str
    stage: str
    reasons: tuple[str, ...]
    fingerprint: str
    payload: dict[str, Any]

    def to_json(self) -> str:
        return json.dumps({
            "status": self.status,
            "stage": self.stage,
            "reasons": self.reasons,
            "fingerprint": self.fingerprint,
            "payload": self.payload
        }, indent=2)


def generate_fingerprint(data: Any) -> str:
    """Deterministic hashing for chain integrity."""
    encoded = json.dumps(data, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalize_evidence_envelope(raw_evidence: dict[str, Any]) -> dict[str, Any]:
    """Adapter to resolve portfolio/evidence-register naming mismatches."""
    normalized = {}
    for key, val in raw_evidence.items():
        # Handle the mismatch where 'status' might be used instead of 'state'
        if isinstance(val, dict):
            mapped_val = dict(val)
            if "status" in mapped_val and "state" not in mapped_val:
                mapped_val["state"] = mapped_val.pop("status")
            normalized[key] = mapped_val
        else:
            normalized[key] = val
    return normalized


def evaluate_consulting_chain(
    workspace_id: str,
    engagement_id: str,
    raw_offers: Sequence[OfferCatalogItem | dict[str, Any]],
    raw_engagement: dict[str, Any],
    raw_economics: dict[str, Any],
    raw_portfolio: dict[str, Any],
    raw_evidence: dict[str, Any],
) -> ChainResult:
    """Evaluate the consulting chain from offers to delivery."""
    try:
        # Stage 1: Offers (using canonical offer catalog structure via typing protocol)
        if not raw_offers:
            return ChainResult("blocked", "offers", ("missing_offers",), generate_fingerprint({}), {})

        validated_offers = []
        for offer in raw_offers:
            # Handle both Protocol objects and dictionaries
            offer_dict = offer if isinstance(offer, dict) else {"type": getattr(offer, "type", "unknown"), "id": getattr(offer, "id", "")}

            if not isinstance(offer_dict, dict):
                raise ConsultingChainError("malformed_offer")

            # Preserve product/service/hybrid classification
            offer_type = offer_dict.get("type", "unknown")
            if offer_type not in {"product", "service", "hybrid", "unknown"}:
                offer_dict["type"] = "unknown"

            validated_offers.append(offer_dict)

        # Stage 2: Engagement
        if not raw_engagement:
            return ChainResult("blocked", "engagement", ("missing_engagement",), generate_fingerprint(validated_offers), {})

        # Bind workspace and artifact store identity
        if raw_engagement.get("workspace_id") != workspace_id:
            raise ConsultingChainError("workspace_identity_mismatch")

        engagement = ConsultingEngagement(**raw_engagement)

        # Stage 3: Economics
        if not raw_economics:
            return ChainResult("blocked", "economics", ("missing_economics",), generate_fingerprint(engagement.to_dict()), {})

        # Keep pricing as planning ranges only
        for key in ["price", "cost", "margin"]:
            if key in raw_economics and not isinstance(raw_economics[key], (list, tuple, dict)):
                raise ConsultingChainError("economics_must_be_ranges")

        # Stage 4: Portfolio
        if not raw_portfolio:
            return ChainResult("blocked", "portfolio", ("missing_portfolio",), generate_fingerprint(raw_economics), {})

        # Stage 5: Evidence Register (with normalized envelope adapter)
        if not raw_evidence:
            return ChainResult("blocked", "evidence", ("missing_evidence",), generate_fingerprint(raw_portfolio), {})

        normalized_evidence = normalize_evidence_envelope(raw_evidence)

        # Preserve missing/conflicting/stale/unavailable evidence states
        allowed_states = {"present", "missing", "conflicting", "stale", "unavailable"}
        for k, v in normalized_evidence.items():
            if isinstance(v, dict) and "state" in v:
                if v["state"] not in allowed_states:
                    raise ConsultingChainError(f"invalid_evidence_state_{v['state']}")

        # Stage 6: Delivery
        reports = {
            "commercial": {"offers": validated_offers},
            "portfolio": raw_portfolio,
            "economics": raw_economics,
        }

        # Use existing packager with workspace leakage check
        deliverable = package_deliverable(engagement, reports, required_reports=("commercial", "portfolio", "economics"))

        payload = {
            "engagement": engagement.to_dict(),
            "deliverable": json.loads(deliverable.to_json())
        }

        return ChainResult(
            status="ready",
            stage="delivery",
            reasons=(),
            fingerprint=generate_fingerprint(payload),
            payload=payload
        )

    except ConsultingChainError as e:
        return ChainResult("failed", "validation", (str(e),), generate_fingerprint(str(e)), {})
    except Exception as e:
        return ChainResult("error", "system", (str(e),), generate_fingerprint(str(e)), {})
