"""Built-in TrustOS policy packs over the canonical control model."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from .control_plane import TrustControl, TrustControlPack, build_policy_packs_from_controls, build_trust_controls
from .mexico_product_compliance import (
    PROMOTION_COMPLIANCE_GATE_ID,
    build_mexico_trust_controls,
    evaluate_mexico_product_compliance,
)


POLICY_PACK_IDS = (
    "security_baseline", "ai_agent_security", "provider_activation",
    "privacy_legal_baseline", "tax_accounting_readiness", "public_launch_readiness",
    "client_trustos_service",
)


def build_policy_packs(*, controls: Sequence[TrustControl] | None = None, seed: Mapping[str, Any] | None = None) -> tuple[TrustControlPack, ...]:
    """Return curated packs; seed is metadata-only and never enables a gate."""
    del seed
    return build_policy_packs_from_controls(tuple(controls or build_trust_controls()))


def build_security_baseline_pack() -> TrustControlPack:
    return next(pack for pack in build_policy_packs() if pack.pack_id == "security_baseline")


def build_ai_agent_security_pack() -> TrustControlPack:
    return next(pack for pack in build_policy_packs() if pack.pack_id == "ai_agent_security")


def build_provider_activation_pack() -> TrustControlPack:
    return next(pack for pack in build_policy_packs() if pack.pack_id == "provider_activation")


def build_privacy_legal_baseline_pack() -> TrustControlPack:
    return next(pack for pack in build_policy_packs() if pack.pack_id == "privacy_legal_baseline")


def build_tax_accounting_readiness_pack() -> TrustControlPack:
    return next(pack for pack in build_policy_packs() if pack.pack_id == "tax_accounting_readiness")


def build_public_launch_readiness_pack() -> TrustControlPack:
    return next(pack for pack in build_policy_packs() if pack.pack_id == "public_launch_readiness")


def build_client_trustos_service_pack() -> TrustControlPack:
    return next(pack for pack in build_policy_packs() if pack.pack_id == "client_trustos_service")


__all__ = [
    "POLICY_PACK_IDS", "PROMOTION_COMPLIANCE_GATE_ID", "build_policy_packs",
    "build_security_baseline_pack", "build_ai_agent_security_pack", "build_provider_activation_pack",
    "build_privacy_legal_baseline_pack", "build_tax_accounting_readiness_pack",
    "build_public_launch_readiness_pack", "build_client_trustos_service_pack",
    "build_mexico_trust_controls", "evaluate_mexico_product_compliance",
]
