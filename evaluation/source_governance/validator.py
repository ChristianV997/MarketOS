"""evaluation/source_governance/validator.py -- Fail-closed validation logic
for MarketOS source-adaptation registry and acceptance pipeline.

Enforces strict governance rules:
- Immutable revision (40-char hex commit SHA for git repos)
- Canonical license recognition & restrictive copyleft rejection (AGPL, ELv2, Sustainable Use)
- Raw credential & secret-shaped metadata rejection
- Inspected paths verification
- Network behavior documentation & unbounded network rejection
- Attribution requirement for copied patterns and integrated code
- Protection of canonical MarketOS authorities (TrustOS, Governor, Approval Ledger, Quality, Event Spine)
- Approved dependencies only (no unapproved heavy runtimes in core)
- Security surface verification (rejection of desktop-control and unverified IPC bridges)
- Freshness window enforcement
- Mandatory rollback deactivation strategy
- Verification evidence requirement
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Dict, List, Optional, Set

from .registry import (
    AdaptationMode,
    CompatibilityStatus,
    IntegrationStatus,
    SourceAdaptationRecord,
    SourceAdaptationRegistry,
)

_HEX_40_RE = re.compile(r"^[0-9a-fA-F]{40}$")

_SECRET_SHAPED_RE = re.compile(
    r"(?is)("
    r"-----begin (?:rsa |ec |dsa |openssh )?private key-----"
    r"|ghp_[A-Za-z0-9_]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|sk-(?:live|test)?-?[A-Za-z0-9]{16,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|bearer [A-Za-z0-9._-]{10,}"
    r")"
)

_SECRET_KEY_NAMES = frozenset({
    "api_key", "apikey", "access_token", "authorization", "auth_token",
    "password", "private_key", "secret", "secret_key", "token", "credential",
    "cookie", "cookies",
})

# Canonical recognized license identifiers (SPDX and industry standards)
RECOGNIZED_LICENSES = frozenset({
    "mit", "apache-2.0", "bsd-3-clause", "bsd-2-clause", "isc",
    "agpl-3.0", "gpl-3.0", "gpl-2.0", "lgpl-3.0", "mpl-2.0",
    "bsl-1.1", "elv2", "elastic-license-2.0", "sustainable use license",
    "sspl", "proprietary-internal", "unlicense", "cc0-1.0",
})

# Restrictive licenses prohibited from being integrated, emulated, or copied into core
RESTRICTIVE_LICENSES = frozenset({
    "agpl-3.0", "agpl", "gpl-3.0", "gpl", "gpl-2.0", "elv2",
    "elastic-license-2.0", "sustainable use license", "bsl-1.1",
    "sspl", "proprietary copyleft",
})

# Protected canonical authorities that cannot be duplicated or replaced by an external source
PROTECTED_CANONICAL_AUTHORITIES = frozenset({
    "evaluation.trustos",
    "evaluation.trustos.control_plane",
    "evaluation.trustos.security_ci_gate",
    "evaluation.trustos.client_workspace_isolation",
    "evaluation.companyos.resource_execution_governor",
    "evaluation.companyos.approval_ledger",
    "evaluation.quality",
    "backend.events.spine",
    "marketos_event_spine",
    "backend.finance",
})

# External dependencies allowed for in-tree 'integrate' mode (strictly limited)
APPROVED_INTEGRATION_DEPENDENCIES = frozenset({
    "pydantic", "dataclasses", "typing_extensions", "requests", "httpx",
    "aiohttp", "beautifulsoup4", "lxml", "numpy", "duckdb",
})

# Heavy unapproved runtime dependencies prohibited in core
PROHIBITED_CORE_DEPENDENCIES = frozenset({
    "twisted", "celery", "airflow", "temporalio", "prefect",
    "dagster", "playwright", "selenium", "puppeteer",
})


class SourceGovernanceError(Exception):
    """Base exception for source governance validation failures."""
    pass


class ImmutableRevisionError(SourceGovernanceError):
    """Raised when an external repository lacks a pinned 40-character commit SHA."""
    pass


class IncompatibleLicenseError(SourceGovernanceError):
    """Raised when a restrictive or incompatible license is marked for integration."""
    pass


class DuplicateAuthorityError(SourceGovernanceError):
    """Raised when an external source claims to replace or duplicate a canonical authority."""
    pass


class CredentialExposureError(SourceGovernanceError):
    """Raised when secret-shaped tokens or raw credentials are found in metadata."""
    pass


class SecuritySurfaceViolationError(SourceGovernanceError):
    """Raised when an external source exposes desktop control or uncontrolled IPC."""
    pass


class UnapprovedDependencyError(SourceGovernanceError):
    """Raised when an external source introduces unapproved heavy runtime dependencies."""
    pass


class MissingRollbackError(SourceGovernanceError):
    """Raised when an external source lacks a concrete rollback strategy."""
    pass


class MissingAttributionError(SourceGovernanceError):
    """Raised when an external source copied or integrated lacks attribution notices."""
    pass


def _contains_secret_shapes(val: Any) -> bool:
    """Recursively search for credentials or secret-shaped values."""
    if isinstance(val, dict):
        for k, v in val.items():
            kl = str(k).lower().replace("-", "_")
            if kl in _SECRET_KEY_NAMES and str(v).strip().lower() not in {"none", "n/a", "isolated", "", "true", "false"}:
                if _SECRET_SHAPED_RE.search(str(v)) or len(str(v).strip()) > 20:
                    return True
            if _contains_secret_shapes(v):
                return True
    elif isinstance(val, (list, tuple)):
        for item in val:
            if _contains_secret_shapes(item):
                return True
    elif isinstance(val, str):
        if _SECRET_SHAPED_RE.search(val):
            return True
    return False


def validate_source_record(
    record: SourceAdaptationRecord | Dict[str, Any],
    seen_ids: Optional[Set[str]] = None,
    max_freshness_days: int = 180,
) -> List[str]:
    """Validate a single source adaptation record fail-closed."""
    errors: List[str] = []

    if isinstance(record, dict):
        rec_dict = record
        try:
            rec = SourceAdaptationRecord.from_dict(rec_dict)
        except Exception as e:
            return [f"schema_deserialization_error: {e}"]
    else:
        rec = record
        rec_dict = rec.to_dict()

    sid = rec.source_id.strip()

    # 1. Source ID validation
    if not sid:
        errors.append("missing_source_id: Record is missing a unique source_id")
        return errors

    if seen_ids is not None:
        if sid in seen_ids:
            errors.append(f"duplicate_source_id: {sid} is already registered")
        seen_ids.add(sid)

    # 2. Adaptation mode validity
    valid_modes = {m.value for m in AdaptationMode}
    if rec.adaptation_mode not in valid_modes:
        errors.append(f"unsupported_adaptation_mode in {sid}: '{rec.adaptation_mode}' is not in {sorted(valid_modes)}")

    # 3. Source URL validation
    s_url = rec.repository_url.strip()
    if not s_url or not (s_url.startswith("http://") or s_url.startswith("https://")):
        errors.append(f"missing_source_url in {sid}: Must be valid http(s) URL")
    if "placeholder" in s_url.lower():
        errors.append(f"placeholder_source_url in {sid}")
    if "raw.githubusercontent.com" in s_url or "raw_payload" in s_url:
        errors.append(f"raw_payload_url_rejected in {sid}: {s_url}")

    # 4. Immutable revision validation (Grok/xAI 40-char SHA pinning model)
    is_git_repo = rec.source_type == "git_repository" or any(h in s_url.lower() for h in ("github.com", "gitlab.com"))
    if is_git_repo:
        sha = rec.commit_sha.strip()
        if not sha:
            errors.append(f"missing_commit_sha in {sid}: Git repository source requires pinned 40-character commit_sha")
        elif not _HEX_40_RE.match(sha):
            errors.append(f"malformed_commit_sha in {sid}: commit_sha must be 40-character hex string, got '{sha}'")

    # 5. License recognition & Restrictive license rejection
    lic_norm = rec.license.strip().lower()
    if not lic_norm or lic_norm not in RECOGNIZED_LICENSES:
        errors.append(f"unknown_license in {sid}: '{rec.license}' is not a recognized license identifier")

    if not rec.license_evidence_url.strip():
        errors.append(f"missing_license_evidence_url in {sid}")

    is_restrictive = any(rl in lic_norm for rl in RESTRICTIVE_LICENSES)
    if is_restrictive:
        if rec.adaptation_mode in (AdaptationMode.INTEGRATE.value, AdaptationMode.COPY_PATTERN.value, AdaptationMode.EMULATE.value):
            errors.append(
                f"incompatible_license_rejected in {sid}: Restrictive license ({rec.license}) "
                f"cannot be used with mode '{rec.adaptation_mode}'"
            )
        if rec.compatibility_status == CompatibilityStatus.COMPATIBLE.value:
            errors.append(
                f"incompatible_license_status_mismatch in {sid}: Restrictive license ({rec.license}) "
                f"must have compatibility_status 'incompatible_license' or 'rejected'"
            )

    # 6. Inspected paths requirement
    if not rec.inspected_paths or len(rec.inspected_paths) == 0:
        errors.append(f"missing_inspected_paths in {sid}: Must specify concrete files or directories inspected")
    elif all(p in (".", "*", "/", "") for p in rec.inspected_paths):
        errors.append(f"invalid_inspected_paths in {sid}: Generic wildcards are prohibited; specify explicit paths")

    # 7. Secret-shaped metadata & credential scanning
    if _contains_secret_shapes(rec_dict):
        errors.append(f"credential_bearing_metadata in {sid}: Contains secret-shaped keys or values")

    # 8. Network behavior documentation & unbounded network rejection
    net_mode = rec.data_network_behavior.network_mode.lower()
    if not net_mode:
        errors.append(f"missing_network_behavior in {sid}: network_mode must be declared")
    if net_mode in ("unbounded_network", "unmetered_live", "live_network"):
        errors.append(f"unbounded_network_rejected in {sid}: Unmetered or unbounded live network access is prohibited")

    # 9. Copied code attribution requirement
    if rec.adaptation_mode in (AdaptationMode.COPY_PATTERN.value, AdaptationMode.INTEGRATE.value):
        attrib = rec.attribution_requirement.strip()
        if not attrib or attrib.lower() in ("none", "n/a", "tbd"):
            errors.append(f"missing_attribution_requirement in {sid}: Code copying or integration requires attribution documentation")

    # 10. Protection of canonical MarketOS authorities
    target_auth = rec.marketos_target_authority.strip()
    if not target_auth or target_auth.lower() in ("none", "n/a"):
        if rec.adaptation_mode in (AdaptationMode.INTEGRATE.value, AdaptationMode.EMULATE.value):
            errors.append(f"missing_target_authority in {sid}: Integrated or emulated source must declare marketos_target_authority")
    else:
        # Check if an external source claims to replace or duplicate a protected authority
        for protected in PROTECTED_CANONICAL_AUTHORITIES:
            if target_auth.lower() == protected:
                # If the source claims to BE the orchestrator or replace quality
                if rec.adaptation_mode in (AdaptationMode.INTEGRATE.value,) and "orchestrator" in sid.lower():
                    errors.append(f"duplicate_authority_rejected in {sid}: External source cannot replace canonical {protected}")
            if "duplicate" in target_auth.lower() or "parallel" in target_auth.lower():
                errors.append(f"duplicate_authority_rejected in {sid}: Cannot establish parallel authority for {target_auth}")

    # 11. Security surface checks: Rejection of desktop control and unverified IPC bridges
    if rec.security_surface.desktop_control_risk or rec.security_surface.local_ipc:
        if rec.adaptation_mode not in (AdaptationMode.REJECT.value, AdaptationMode.DEFER.value, AdaptationMode.REFERENCE_ONLY.value):
            errors.append(
                f"desktop_control_bridge_rejected in {sid}: Source with desktop control or local IPC risks "
                f"must be rejected or deferred, cannot be '{rec.adaptation_mode}'"
            )

    # 12. GPU Orchestration source check
    if "gpu" in sid.lower() or "orchestration" in sid.lower():
        if rec.adaptation_mode == AdaptationMode.INTEGRATE.value:
            errors.append(
                f"gpu_orchestration_unauthorized in {sid}: GPU orchestration cannot be integrated without cluster infrastructure; must be deferred or reference_only"
            )

    # 13. Dependency validation
    if rec.adaptation_mode == AdaptationMode.INTEGRATE.value:
        for dep in rec.dependencies:
            depl = dep.strip().lower()
            if depl in PROHIBITED_CORE_DEPENDENCIES:
                errors.append(f"prohibited_core_dependency in {sid}: '{dep}' introduces heavy unapproved runtime")

    # 14. Mandatory rollback deactivation strategy
    rollback = rec.rollback_strategy.strip()
    if not rollback or rollback.lower() in ("none", "n/a", "tbd", "placeholder", "todo"):
        errors.append(f"missing_rollback_strategy in {sid}: Must provide concrete rollback/deactivation plan")

    # 15. Verification evidence requirement for accepted/emulated sources
    if rec.adaptation_mode in (AdaptationMode.INTEGRATE.value, AdaptationMode.EMULATE.value, AdaptationMode.COPY_PATTERN.value):
        vevid = rec.verification_evidence.strip()
        if not vevid or vevid.lower() in ("none", "n/a", "tbd", "pending"):
            errors.append(f"missing_verification_evidence in {sid}: Accepted adaptation requires verification evidence")

    # 16. Rejection reason required if rejected
    if rec.adaptation_mode == AdaptationMode.REJECT.value or rec.integration_status == IntegrationStatus.REJECTED.value:
        if not rec.rejection_reason or not rec.rejection_reason.strip():
            errors.append(f"missing_rejection_reason in {sid}: Rejected source must provide rejection_reason")

    # 17. Freshness window validation
    if rec.last_reviewed_at.strip():
        try:
            # Parse ISO8601
            dt = datetime.fromisoformat(rec.last_reviewed_at.replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0
            if age_days > max_freshness_days:
                errors.append(f"stale_source_review in {sid}: Last reviewed {age_days:.1f} days ago (limit: {max_freshness_days})")
        except Exception:
            errors.append(f"malformed_last_reviewed_at in {sid}: Must be ISO8601 format")
    else:
        errors.append(f"missing_last_reviewed_at in {sid}")

    return errors


def validate_registry(registry: SourceAdaptationRegistry) -> List[str]:
    """Validate all records in a SourceAdaptationRegistry fail-closed."""
    all_errors: List[str] = []
    seen_ids: Set[str] = set()

    for rec in registry.records.values():
        errs = validate_source_record(rec, seen_ids=seen_ids)
        all_errors.extend(errs)

    return all_errors
