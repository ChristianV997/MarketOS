"""Supplier and Logistics Intelligence.

Evaluates supplier feasibility, logistics, and unit economics constraints
for consulting engagements. This ensures the delivery packager has
canonical access to validated supplier information.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Sequence

from evaluation.commerce.supplier_feasibility import SupplierFeasibilityReport
from evaluation.trustos.client_workspace_isolation import check_workspace_leakage

class SupplierLogisticsError(ValueError):
    """Failure evaluating supplier and logistics evidence."""


@dataclass
class SupplierLogisticsResult:
    status: str
    reasons: tuple[str, ...]
    payload: dict[str, Any]
    fingerprint: str

    def to_json(self) -> str:
        return json.dumps({
            "status": self.status,
            "reasons": self.reasons,
            "payload": self.payload,
            "fingerprint": self.fingerprint
        }, indent=2)

    def to_markdown(self) -> str:
        return f"# Supplier Logistics Result\n\nStatus: {self.status}\nFingerprint: {self.fingerprint}\n\n```json\n{json.dumps(self.payload, indent=2)}\n```"

def _generate_fingerprint(data: Any) -> str:
    """Deterministic hashing for chain integrity."""
    encoded = json.dumps(data, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

def evaluate_supplier_logistics(
    raw_offers: Sequence[dict[str, Any]],
    supplier_evidence: SupplierFeasibilityReport | dict[str, Any] | None,
) -> SupplierLogisticsResult:
    """Evaluate supplier and logistics feasibility for a consulting engagement."""

    if not raw_offers:
        return SupplierLogisticsResult("blocked", ("missing_offers",), {}, _generate_fingerprint({}))

    try:
        # Normalize evidence input
        if supplier_evidence is None:
            evidence_data = {}
        elif isinstance(supplier_evidence, dict):
            # Parse dict back into expected format or treat as raw
            evidence_data = supplier_evidence
        elif hasattr(supplier_evidence, "to_dict"):
            evidence_data = supplier_evidence.to_dict()
        else:
            return SupplierLogisticsResult("blocked", ("invalid_supplier_evidence_format",), {}, _generate_fingerprint({}))

        # We must support explicit missing vs unprovided states
        evidence_mode = evidence_data.get("evidence_mode", "unknown") if evidence_data else "missing"
        if evidence_mode not in {"fixture", "simulated", "stale", "missing", "conflicting", "manual"}:
            # Normalize live claims to unavailable per architecture rules unless admissible
            evidence_mode = "unavailable"

        processed_offers = []
        for offer in raw_offers:
            # Explicit allowlist of allowed fields to prevent raw payload/credential leakage
            processed_offer = {
                "candidate_id": offer.get("candidate_id"),
                "type": offer.get("type", "unknown"),
            }

            # Require candidate-bound supplier identity
            if not processed_offer["candidate_id"]:
                raise SupplierLogisticsError("missing_candidate_identity")

            # Classify offering type
            if processed_offer["type"] not in {"goods", "service", "hybrid", "unknown"}:
                processed_offer["type"] = "unknown"

            # Validate cost boundaries. Explicitly check if the key exists and value is not None
            if "unit_cost" not in offer or offer["unit_cost"] is None:
                raise SupplierLogisticsError("missing_unit_cost")
            processed_offer["unit_cost"] = offer["unit_cost"]

            if "shipping_cost" not in offer or offer["shipping_cost"] is None:
                 # Explicit zero shipping is allowed, but missing key or None value is not
                raise SupplierLogisticsError("missing_shipping_cost")
            processed_offer["shipping_cost"] = offer["shipping_cost"]

            # Handle additional logistics fields if present
            for extra in ("customs_cost", "handling_cost", "delivery_days", "capacity"):
                if extra in offer:
                    processed_offer[extra] = offer[extra]

            # Check for currency mismatch if currencies are provided
            curr1 = offer.get("currency")
            curr2 = evidence_data.get("currency")
            if curr1 and curr2 and curr1 != curr2:
                raise SupplierLogisticsError("currency_mismatch")
            processed_offer["currency"] = curr1

            processed_offers.append(processed_offer)

        payload = {
            "offers": processed_offers,
            "evidence_mode": evidence_mode,
            "suppliers_observed": evidence_data.get("suppliers_observed", [])
        }

        # Cross-workspace isolation and credential leakage rejection
        try:
            leakage = check_workspace_leakage(payload, client_safe=True)
            if leakage:
                raise ValueError(f"Workspace isolation violation: {leakage}")
        except Exception as e:
            raise SupplierLogisticsError("workspace_isolation_failed")

        return SupplierLogisticsResult(
            status="ready",
            reasons=(),
            payload=payload,
            fingerprint=_generate_fingerprint(payload)
        )

    except SupplierLogisticsError as e:
        return SupplierLogisticsResult("failed", (str(e),), {}, _generate_fingerprint(str(e)))
    except Exception as e:
        return SupplierLogisticsResult("error", (str(e),), {}, _generate_fingerprint(str(e)))
