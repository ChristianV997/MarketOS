"""Deterministic per-market product-compliance section for ProductValidationReport.

This module is not a new compliance gate, registry, or legal engine. It is
a thin, pure decision layer over evidence the caller supplies (or omits)
for each candidate, mirroring the fixture/live evidence-state philosophy
already canonical in ``evaluation.commerce.promotion``
(``FIXTURE_EVIDENCE_CEILING``, ``backend.economics.kernel.EVIDENCE_STATES``):
fixture/manual/unknown evidence can support screening but can never itself
justify a ``compliant`` conclusion. ``evaluation.commerce.promotion``'s
reserved ``"compliance"`` gate id remains the single promotion-facing
authority for whether a candidate may advance; this module only produces
the evidence-backed status detail a caller (or that gate) can consume.

Mexico is the only market evaluated today. The United States and Canada
are always ``not_assessed`` -- this module never evaluates a requirement
for them, regardless of what evidence a caller supplies for those keys.

No HS code, tariff classification, certificate, or legal conclusion is
ever guessed, inferred, or fetched: every status is derived only from
evidence fields the caller explicitly supplies. An absent field always
resolves to ``needs_evidence``, never a guessed ``compliant``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from backend.economics.kernel import EVIDENCE_STATES

# Closed status vocabulary. "compliant" is reachable only for a
# live/observed/verified evidence state with matching, unexpired,
# non-cancelled evidence for that requirement.
STATUSES: tuple[str, ...] = ("not_assessed", "needs_evidence", "blocked", "compliant")

ASSESSED_MARKETS: tuple[str, ...] = ("MX",)
NOT_ASSESSED_MARKETS: tuple[str, ...] = ("US", "CA")
ALL_MARKETS: tuple[str, ...] = ASSESSED_MARKETS + NOT_ASSESSED_MARKETS

_LIVE_EVIDENCE_STATES = {"observed", "live_readonly", "verified"}

# Mexico requirement ids. "ift_crt_homologation" is a radio-homologation
# requirement and only applies to radio-emitting candidates -- see
# _requirements_for_candidate.
_MX_REQUIREMENTS: tuple[str, ...] = (
    "exact_sku_model_match",
    "tariff_classification",
    "nom_applicability",
    "ift_crt_homologation",
    "customs_import_permit",
)

_BAD_CERT_STATES = {"expired", "cancelled", "mismatched", "stale", "revoked"}
_GOOD_CERT_STATES = {"active", "current", "valid"}
_RADIO_CATEGORY_MARKERS = ("radio", "wireless", "bluetooth", "wifi", "wi-fi", "cellular", "rf_", "lte", "5g")


@dataclass(frozen=True)
class ComplianceRequirementResult:
    market: str
    requirement: str
    status: str
    evidence: str
    source: str
    access_date: str
    missing_input: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "market": self.market,
            "requirement": self.requirement,
            "status": self.status,
            "evidence": self.evidence,
            "source": self.source,
            "access_date": self.access_date,
            "missing_input": list(self.missing_input),
        }


def _is_radio_emitting(candidate: Mapping[str, Any]) -> bool:
    flag = candidate.get("is_radio_emitting")
    if isinstance(flag, bool):
        return flag
    category = str(candidate.get("category") or candidate.get("product_category") or "").lower()
    return any(marker in category for marker in _RADIO_CATEGORY_MARKERS)


def _requirements_for_candidate(candidate: Mapping[str, Any]) -> tuple[str, ...]:
    """Radio-homologation only applies to radio-emitting products -- a
    non-radio candidate never has ``ift_crt_homologation`` in its
    requirement set, so it can never be blocked or held on that rule."""
    if _is_radio_emitting(candidate):
        return _MX_REQUIREMENTS
    return tuple(r for r in _MX_REQUIREMENTS if r != "ift_crt_homologation")


def _evidence_field(req_evidence: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        value = req_evidence.get(name)
        if value not in (None, ""):
            return value
    return None


_TRUE_TOKENS = {"true", "yes", "match", "matched", "applicable"}
_FALSE_TOKENS = {"false", "no", "mismatch", "not_applicable"}


def _tri_state(value: Any) -> str:
    """Fail-closed tri-state read of a boolean-ish evidence field.

    Returns ``"true"``/``"false"`` only for an explicit boolean or an
    exactly recognized token; any other value (an unrecognized string, a
    number, ``"TBD"``, etc.) returns ``"unknown"`` rather than being
    guessed as a match/applicability -- ambiguous evidence must never be
    silently treated as a positive result.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    token = str(value).strip().lower()
    if token in _TRUE_TOKENS:
        return "true"
    if token in _FALSE_TOKENS:
        return "false"
    return "unknown"


def _requirement_status(requirement: str, req_evidence: Mapping[str, Any], evidence_state: str) -> tuple[str, tuple[str, ...]]:
    """Return (status, missing_input) for one requirement.

    Never guesses: a requirement can only reach ``compliant`` when its own
    evidence fields are present and good AND the aggregate evidence_state
    for the market is live/observed/verified. Fixture/manual/unknown
    evidence state caps every requirement at ``needs_evidence`` at best,
    exactly as ``promotion.FIXTURE_EVIDENCE_CEILING`` caps promotion
    stages for the same evidence states.
    """
    is_live = evidence_state in _LIVE_EVIDENCE_STATES

    if requirement == "exact_sku_model_match":
        match = _evidence_field(req_evidence, "match", "sku_match", "model_match")
        if match is None:
            return "needs_evidence", ("exact_sku_or_model_match",)
        state = _tri_state(match)
        if state == "false":
            return "blocked", ()
        if state == "unknown":
            return "needs_evidence", ("exact_sku_or_model_match",)
        return ("compliant" if is_live else "needs_evidence"), ()

    if requirement == "tariff_classification":
        hs_code = _evidence_field(req_evidence, "hs_code", "tariff_code")
        if not hs_code:
            return "needs_evidence", ("hs_code",)
        return ("compliant" if is_live else "needs_evidence"), ()

    if requirement == "nom_applicability":
        applicable = _evidence_field(req_evidence, "applicable", "nom_applicable")
        if applicable is None:
            return "needs_evidence", ("nom_applicability_determination",)
        state = _tri_state(applicable)
        if state == "unknown":
            return "needs_evidence", ("nom_applicability_determination",)
        if state == "true":
            nom_status = _evidence_field(req_evidence, "nom_status", "certificate_status")
            if not nom_status:
                return "needs_evidence", ("nom_certificate_status",)
            status_l = str(nom_status).lower()
            if status_l in _BAD_CERT_STATES:
                return "blocked", ()
            if status_l in _GOOD_CERT_STATES:
                return ("compliant" if is_live else "needs_evidence"), ()
            return "needs_evidence", ("nom_certificate_status",)
        return ("compliant" if is_live else "needs_evidence"), ()

    if requirement == "ift_crt_homologation":
        cert_status = _evidence_field(req_evidence, "certificate_status", "homologation_status")
        if not cert_status:
            return "needs_evidence", ("ift_crt_certificate_status",)
        status_l = str(cert_status).lower()
        if status_l in _BAD_CERT_STATES:
            return "blocked", ()
        if status_l in _GOOD_CERT_STATES:
            return ("compliant" if is_live else "needs_evidence"), ()
        return "needs_evidence", ("ift_crt_certificate_status",)

    if requirement == "customs_import_permit":
        permit_status = _evidence_field(req_evidence, "status", "permit_status")
        if not permit_status:
            return "needs_evidence", ("customs_import_permit_status",)
        status_l = str(permit_status).lower()
        if status_l in {"denied", "revoked", "expired", "rejected", "cancelled"}:
            return "blocked", ()
        if status_l in {"granted", "approved", "active"}:
            return ("compliant" if is_live else "needs_evidence"), ()
        return "needs_evidence", ("customs_import_permit_status",)

    return "needs_evidence", (requirement,)


def evaluate_candidate_market_compliance(
    candidate: Mapping[str, Any], market_evidence: Mapping[str, Any] | None = None
) -> tuple[dict[str, Any], ...]:
    """Return one result dict per (market, requirement) for a candidate.

    US and Canada always come back ``not_assessed`` regardless of any
    evidence supplied under those keys. Mexico requirements are evaluated
    only from caller-supplied evidence -- nothing is fetched, inferred, or
    guessed.
    """
    market_evidence = dict(market_evidence or {})
    results: list[dict[str, Any]] = []

    for market in NOT_ASSESSED_MARKETS:
        results.append(
            ComplianceRequirementResult(
                market=market,
                requirement="market_compliance",
                status="not_assessed",
                evidence="not_assessed_market",
                source="",
                access_date="",
                missing_input=(),
            ).to_dict()
        )

    for market in ASSESSED_MARKETS:
        m_evidence = dict(market_evidence.get(market) or {})
        evidence_state = str(m_evidence.get("evidence_state") or "unknown")
        if evidence_state not in EVIDENCE_STATES:
            evidence_state = "unknown"
        requirements_map = dict(m_evidence.get("requirements") or {})
        for requirement in _requirements_for_candidate(candidate):
            req_evidence = dict(requirements_map.get(requirement) or {})
            status, missing = _requirement_status(requirement, req_evidence, evidence_state)
            evidence_summary = str(
                req_evidence.get("summary")
                or req_evidence.get("evidence")
                or ("no_evidence_supplied" if not req_evidence else "evidence_supplied")
            )
            results.append(
                ComplianceRequirementResult(
                    market=market,
                    requirement=requirement,
                    status=status,
                    evidence=evidence_summary,
                    source=str(req_evidence.get("source") or ""),
                    access_date=str(req_evidence.get("access_date") or ""),
                    missing_input=missing,
                ).to_dict()
            )
    return tuple(results)


def build_market_compliance_section(
    candidates: Sequence[Mapping[str, Any]], market_compliance_evidence: Mapping[str, Any] | None = None
) -> tuple[dict[str, Any], ...]:
    """Build the per-candidate market-compliance section for the report.

    ``market_compliance_evidence`` maps a candidate id to its
    caller-supplied per-market evidence (see
    ``evaluate_candidate_market_compliance``). Every candidate gets a full
    section even with no supplied evidence -- requirements simply resolve
    to ``needs_evidence`` (or ``not_assessed`` for US/CA) rather than the
    section being omitted.
    """
    market_compliance_evidence = dict(market_compliance_evidence or {})
    sections: list[dict[str, Any]] = []
    for candidate in candidates:
        inner = candidate.get("candidate") if isinstance(candidate.get("candidate"), Mapping) else candidate
        candidate_id = str(inner.get("id") or inner.get("candidate_id") or inner.get("title") or "")
        requirements = evaluate_candidate_market_compliance(inner, market_compliance_evidence.get(candidate_id))
        assessed_statuses = {r["status"] for r in requirements if r["market"] in ASSESSED_MARKETS}
        if "blocked" in assessed_statuses:
            overall = "blocked"
        elif not assessed_statuses or "needs_evidence" in assessed_statuses:
            overall = "needs_evidence"
        else:
            overall = "compliant"
        sections.append(
            {
                "candidate_id": candidate_id,
                "requirements": requirements,
                "overall_status": overall,
            }
        )
    return tuple(sections)


__all__ = [
    "STATUSES",
    "ASSESSED_MARKETS",
    "NOT_ASSESSED_MARKETS",
    "ALL_MARKETS",
    "ComplianceRequirementResult",
    "evaluate_candidate_market_compliance",
    "build_market_compliance_section",
]
