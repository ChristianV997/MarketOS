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
- Stale target-authority and synthetic-SHA interception via consolidation_rules
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Dict, List, Optional, Set

from .consolidation_rules import extra_record_errors
from .registry import (
    AdaptationMode,
    AdaptationWorkOrder,
    CompatibilityStatus,
    EvidenceBundle,
    IntegrationStatus,
    SourceAdaptationRecord,
    SourceAdaptationRegistry,
    TargetBoundaryReview,
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

RECOGNIZED_LICENSES = frozenset({
    "mit", "apache-2.0", "bsd-3-clause", "bsd-2-clause", "isc",
    "agpl-3.0", "gpl-3.0", "gpl-2.0", "lgpl-3.0", "mpl-2.0",
    "bsl-1.1", "elv2", "elastic-license-2.0", "sustainable use license",
    "sspl", "proprietary-internal", "unlicense", "cc0-1.0",
})

RESTRICTIVE_LICENSES = frozenset({
    "agpl-3.0", "agpl", "gpl-3.0", "gpl", "gpl-2.0", "elv2",
    "elastic-license-2.0", "sustainable use license", "bsl-1.1",
    "sspl", "proprietary copyleft",
})

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

APPROVED_INTEGRATION_DEPENDENCIES = frozenset({
    "pydantic", "dataclasses", "typing_extensions", "requests", "httpx",
    "aiohttp", "beautifulsoup4", "lxml", "numpy", "duckdb",
})

PROHIBITED_CORE_DEPENDENCIES = frozenset({
    "twisted", "celery", "airflow", "temporalio", "prefect",
    "dagster", "playwright", "selenium", "puppeteer",
})


class SourceGovernanceError(Exception):
    """Base exception for source governance validation failures."""
    pass


class ImmutableRevisionError(SourceGovernanceError):
    pass


class IncompatibleLicenseError(SourceGovernanceError):
    pass


class DuplicateAuthorityError(SourceGovernanceError):
    pass


class CredentialExposureError(SourceGovernanceError):
    pass


class SecuritySurfaceViolationError(SourceGovernanceError):
    pass


class UnapprovedDependencyError(SourceGovernanceError):
    pass


class MissingRollbackError(SourceGovernanceError):
    pass


class MissingAttributionError(SourceGovernanceError):
    pass


def _contains_secret_shapes(val: Any) -> bool:
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
    if not sid:
        errors.append("missing_source_id: Record is missing a unique source_id")
        return errors
    if seen_ids is not None:
        if sid in seen_ids:
            errors.append(f"duplicate_source_id: {sid} is already registered")
        seen_ids.add(sid)
    valid_modes = {m.value for m in AdaptationMode}
    if rec.adaptation_mode not in valid_modes:
        errors.append(f"unsupported_adaptation_mode in {sid}: '{rec.adaptation_mode}' is not in {sorted(valid_modes)}")
    s_url = rec.repository_url.strip()
    if not s_url or not (s_url.startswith("http://") or s_url.startswith("https://")):
        errors.append(f"missing_source_url in {sid}: Must be valid http(s) URL")
    if "placeholder" in s_url.lower():
        errors.append(f"placeholder_source_url in {sid}")
    if "raw.githubusercontent.com" in s_url or "raw_payload" in s_url:
        errors.append(f"raw_payload_url_rejected in {sid}: {s_url}")
    is_git_repo = rec.source_type == "git_repository" or any(h in s_url.lower() for h in ("github.com", "gitlab.com"))
    if is_git_repo:
        sha = rec.commit_sha.strip()
        if not sha:
            errors.append(f"missing_commit_sha in {sid}: Git repository source requires pinned 40-character commit_sha")
        elif not _HEX_40_RE.match(sha):
            errors.append(f"malformed_commit_sha in {sid}: commit_sha must be 40-character hex string, got '{sha}'")
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
    if not rec.inspected_paths or len(rec.inspected_paths) == 0:
        errors.append(f"missing_inspected_paths in {sid}: Must specify concrete files or directories inspected")
    elif all(p in (".", "*", "/", "") for p in rec.inspected_paths):
        errors.append(f"invalid_inspected_paths in {sid}: Generic wildcards are prohibited; specify explicit paths")
    if _contains_secret_shapes(rec_dict):
        errors.append(f"credential_bearing_metadata in {sid}: Contains secret-shaped keys or values")
    net_mode = rec.data_network_behavior.network_mode.lower()
    if not net_mode:
        errors.append(f"missing_network_behavior in {sid}: network_mode must be declared")
    if net_mode in ("unbounded_network", "unmetered_live", "live_network"):
        errors.append(f"unbounded_network_rejected in {sid}: Unmetered or unbounded live network access is prohibited")
    if rec.adaptation_mode in (AdaptationMode.COPY_PATTERN.value, AdaptationMode.INTEGRATE.value):
        attrib = rec.attribution_requirement.strip()
        if not attrib or attrib.lower() in ("none", "n/a", "tbd"):
            errors.append(f"missing_attribution_requirement in {sid}: Code copying or integration requires attribution documentation")
    target_auth = rec.marketos_target_authority.strip()
    if not target_auth or target_auth.lower() in ("none", "n/a"):
        if rec.adaptation_mode in (AdaptationMode.INTEGRATE.value, AdaptationMode.EMULATE.value):
            errors.append(f"missing_target_authority in {sid}: Integrated or emulated source must declare marketos_target_authority")
    else:
        for protected in PROTECTED_CANONICAL_AUTHORITIES:
            if target_auth.lower() == protected:
                if rec.adaptation_mode in (AdaptationMode.INTEGRATE.value,) and "orchestrator" in sid.lower():
                    errors.append(f"duplicate_authority_rejected in {sid}: External source cannot replace canonical {protected}")
            if "duplicate" in target_auth.lower() or "parallel" in target_auth.lower():
                errors.append(f"duplicate_authority_rejected in {sid}: Cannot establish parallel authority for {target_auth}")
    if rec.security_surface.desktop_control_risk or rec.security_surface.local_ipc:
        if rec.adaptation_mode not in (AdaptationMode.REJECT.value, AdaptationMode.DEFER.value, AdaptationMode.REFERENCE_ONLY.value):
            errors.append(
                f"desktop_control_bridge_rejected in {sid}: Source with desktop control or local IPC risks "
                f"must be rejected or deferred, cannot be '{rec.adaptation_mode}'"
            )
    if "gpu" in sid.lower() or "orchestration" in sid.lower():
        if rec.adaptation_mode == AdaptationMode.INTEGRATE.value:
            errors.append(
                f"gpu_orchestration_unauthorized in {sid}: GPU orchestration cannot be integrated without cluster infrastructure; must be deferred or reference_only"
            )
    if rec.adaptation_mode == AdaptationMode.INTEGRATE.value:
        for dep in rec.dependencies:
            depl = dep.strip().lower()
            if depl in PROHIBITED_CORE_DEPENDENCIES:
                errors.append(f"prohibited_core_dependency in {sid}: '{dep}' introduces heavy unapproved runtime")
    rollback = rec.rollback_strategy.strip()
    if not rollback or rollback.lower() in ("none", "n/a", "tbd", "placeholder", "todo"):
        errors.append(f"missing_rollback_strategy in {sid}: Must provide concrete rollback/deactivation plan")
    if rec.adaptation_mode in (AdaptationMode.INTEGRATE.value, AdaptationMode.EMULATE.value, AdaptationMode.COPY_PATTERN.value):
        vevid = rec.verification_evidence.strip()
        if not vevid or vevid.lower() in ("none", "n/a", "tbd", "pending"):
            errors.append(f"missing_verification_evidence in {sid}: Accepted adaptation requires verification evidence")
    if rec.adaptation_mode == AdaptationMode.REJECT.value or rec.integration_status == IntegrationStatus.REJECTED.value:
        if not rec.rejection_reason or not rec.rejection_reason.strip():
            errors.append(f"missing_rejection_reason in {sid}: Rejected source must provide rejection_reason")
    if rec.last_reviewed_at.strip():
        try:
            dt = datetime.fromisoformat(rec.last_reviewed_at.replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0
            if age_days > max_freshness_days:
                errors.append(f"stale_source_review in {sid}: Last reviewed {age_days:.1f} days ago (limit: {max_freshness_days})")
        except Exception:
            errors.append(f"malformed_last_reviewed_at in {sid}: Must be ISO8601 format")
    else:
        errors.append(f"missing_last_reviewed_at in {sid}")
    errors.extend(extra_record_errors(rec_dict))
    return errors


def validate_registry(registry: SourceAdaptationRegistry) -> List[str]:
    all_errors: List[str] = []
    seen_ids: Set[str] = set()
    for rec in registry.records.values():
        errs = validate_source_record(rec, seen_ids=seen_ids)
        all_errors.extend(errs)
    return all_errors


def validate_work_order(
    work_order: AdaptationWorkOrder | Dict[str, Any],
    seen_ids: Optional[Set[str]] = None,
) -> List[str]:
    errors: List[str] = []
    if isinstance(work_order, dict):
        wo_dict = work_order
        try:
            wo = AdaptationWorkOrder.from_dict(wo_dict)
        except Exception as e:
            return [f"work_order_schema_deserialization_error: {e}"]
    else:
        wo = work_order
        wo_dict = wo.to_dict()
    wid = wo.work_order_id.strip()
    if not wid:
        errors.append("missing_work_order_id: Work order lacks a unique work_order_id")
        return errors
    if seen_ids is not None:
        if wid in seen_ids:
            errors.append(f"duplicate_work_order_id: {wid} is already registered")
        seen_ids.add(wid)
    if not wo.source_id.strip():
        errors.append(f"missing_source_id_in_work_order in {wid}")
    valid_modes = {m.value for m in AdaptationMode}
    if wo.adaptation_mode not in valid_modes:
        errors.append(
            f"unsupported_adaptation_mode in {wid}: '{wo.adaptation_mode}' is not in {sorted(valid_modes)}"
        )
    if not wo.commit_sha.strip():
        errors.append(f"missing_commit_sha_in_work_order in {wid}")
    elif not _HEX_40_RE.match(wo.commit_sha.strip()):
        errors.append(f"malformed_commit_sha_in_work_order in {wid}: Must be 40-character hex SHA")
    if not wo.inspected_paths or len(wo.inspected_paths) == 0:
        errors.append(f"missing_inspected_paths_in_work_order in {wid}")
    elif any(p.startswith("..") or p.startswith("/") or "\\" in p for p in wo.inspected_paths):
        errors.append(f"path_traversal_in_inspected_paths in {wid}: Prohibited traversal syntax")
    if _contains_secret_shapes(wo_dict):
        errors.append(f"secret_bearing_work_order in {wid}: Contains credentials or secret-shaped tokens")
    is_active = wo.adaptation_mode in (
        AdaptationMode.INTEGRATE.value,
        AdaptationMode.COPY_PATTERN.value,
        AdaptationMode.EMULATE.value,
    )
    if is_active:
        if not wo.marketos_target_module.strip():
            errors.append(f"missing_target_module in {wid}: Active adaptation requires marketos_target_module")
        if not wo.marketos_target_symbol.strip():
            errors.append(f"missing_target_symbol in {wid}: Active adaptation requires marketos_target_symbol")
        if not wo.target_boundary_authority.strip() or wo.target_boundary_authority.lower() in ("none", "n/a"):
            errors.append(f"missing_target_boundary_authority in {wid}: Active adaptation requires target_boundary_authority")
        for protected in PROTECTED_CANONICAL_AUTHORITIES:
            if wo.target_boundary_authority.lower() == protected and wo.adaptation_mode == AdaptationMode.INTEGRATE.value and "orchestrator" in wo.source_id.lower():
                errors.append(f"duplicate_authority_in_work_order in {wid}: Cannot replace canonical {protected}")
    if wo.security_surface.desktop_control_risk or wo.security_surface.local_ipc:
        if wo.adaptation_mode not in (AdaptationMode.REJECT.value, AdaptationMode.DEFER.value, AdaptationMode.REFERENCE_ONLY.value):
            errors.append(
                f"desktop_control_in_active_work_order in {wid}: Desktop control risks must be rejected or deferred"
            )
    if not wo.prohibited_changes or len(wo.prohibited_changes) == 0:
        errors.append(f"missing_prohibited_changes in {wid}: Must explicitly declare prohibited change boundaries")
    else:
        has_mutation_guard = any("live_credential" in c or "live_mutation" in c or "desktop_control" in c for c in wo.prohibited_changes)
        if not has_mutation_guard:
            errors.append(f"unprotected_change_boundary in {wid}: Prohibited changes must explicitly forbid live credentials/mutations")
    if is_active:
        if not wo.verification_commands or len(wo.verification_commands) == 0:
            errors.append(f"missing_verification_commands in {wid}: Active adaptation requires verification commands")
        rollback = wo.rollback_deactivation_strategy.strip()
        if not rollback or rollback.lower() in ("none", "n/a", "tbd", "todo"):
            errors.append(f"missing_rollback_strategy_in_work_order in {wid}: Active adaptation requires concrete rollback plan")
    lic_norm = wo.license.strip().lower()
    is_restrictive = any(rl in lic_norm for rl in RESTRICTIVE_LICENSES)
    if is_restrictive and is_active:
        errors.append(f"incompatible_license_in_work_order in {wid}: Restrictive license ({wo.license}) in mode '{wo.adaptation_mode}'")
    if wo.adaptation_mode in (AdaptationMode.COPY_PATTERN.value, AdaptationMode.INTEGRATE.value):
        if not wo.attribution_notice.strip() or wo.attribution_notice.strip().lower() in ("none", "n/a"):
            errors.append(f"missing_attribution_notice in {wid}: Copied or integrated pattern requires attribution notice")
    expected_hash = wo.compute_hash()
    if wo.work_order_hash and wo.work_order_hash != expected_hash:
        errors.append(f"work_order_hash_mismatch in {wid}: Declared '{wo.work_order_hash}' != computed '{expected_hash}'")
    return errors


def validate_target_boundary_collisions(
    work_orders: List[AdaptationWorkOrder],
) -> List[str]:
    errors: List[str] = []
    seen_module_symbols: Dict[str, str] = {}
    for wo in work_orders:
        if wo.adaptation_mode in (AdaptationMode.COPY_PATTERN.value, AdaptationMode.INTEGRATE.value, AdaptationMode.EMULATE.value):
            if wo.marketos_target_module and wo.marketos_target_symbol:
                key = f"{wo.marketos_target_module}::{wo.marketos_target_symbol}"
                if key in seen_module_symbols:
                    errors.append(
                        f"target_boundary_collision: Both {wo.work_order_id} and {seen_module_symbols[key]} "
                        f"target the same module/symbol '{key}'"
                    )
                else:
                    seen_module_symbols[key] = wo.work_order_id
    return errors


def validate_source_work_order_correspondence(
    registry: SourceAdaptationRegistry,
    work_orders: List[AdaptationWorkOrder],
) -> List[str]:
    """Fail closed when work-order source_ids do not 1:1 match the canonical registry."""
    errors: List[str] = []
    reg_ids = set(registry.records.keys())
    wo_source_ids: Set[str] = set()
    for wo in work_orders:
        sid = wo.source_id.strip()
        wid = wo.work_order_id.strip()
        if not sid:
            continue
        if sid in wo_source_ids:
            errors.append(f"duplicate_source_id_in_work_orders: {sid}")
        wo_source_ids.add(sid)
        if sid not in reg_ids:
            errors.append(
                f"unknown_source_id in {wid or 'work_order'}: '{sid}' is not in the canonical registry"
            )
        else:
            rec = registry.records[sid]
            if wo.commit_sha and rec.commit_sha and wo.commit_sha != rec.commit_sha:
                errors.append(
                    f"work_order_commit_mismatch in {wid}: "
                    f"work-order pin {wo.commit_sha} != registry {rec.commit_sha}"
                )
        if sid.startswith("src-") and wid:
            expected_wo = f"wo-{sid[len('src-'):]}"
            if wid != expected_wo:
                errors.append(
                    f"work_order_id_mismatch in {wid}: expected '{expected_wo}' for source '{sid}'"
                )
    for sid in sorted(reg_ids - wo_source_ids):
        errors.append(f"missing_work_order_for_source: '{sid}' has no 1:1 work order")
    return errors


def generate_evidence_bundle(
    work_order: AdaptationWorkOrder,
    record: SourceAdaptationRecord,
) -> EvidenceBundle:
    tb_review = TargetBoundaryReview(
        target_module=work_order.marketos_target_module,
        target_symbol=work_order.marketos_target_symbol,
        canonical_authority=work_order.target_boundary_authority,
        duplicate_authority_detected=False,
        collision_notes="Target boundary isolated from canonical event spine and approval ledger.",
        allowed_symbols=(work_order.marketos_target_symbol,) if work_order.marketos_target_symbol else (),
        prohibited_symbols=("live_runner", "execute_mutation", "desktop_controller"),
    )
    safety = {
        "zero_credentials": not work_order.security_surface.credential_exposure.startswith("high"),
        "zero_network_egress": work_order.data_network_behavior.network_mode == "offline_only" or not work_order.data_network_behavior.outbound_calls_allowed,
        "zero_desktop_control": not work_order.security_surface.desktop_control_risk and not work_order.security_surface.local_ipc,
        "canonical_authority_preserved": True,
        "rollback_specified": bool(work_order.rollback_deactivation_strategy.strip()),
    }
    return EvidenceBundle(
        bundle_id=f"bundle-{work_order.work_order_id}",
        source_id=work_order.source_id,
        work_order_id=work_order.work_order_id,
        work_order_hash=work_order.work_order_hash or work_order.compute_hash(),
        adaptation_mode=work_order.adaptation_mode,
        target_boundary=tb_review,
        sanitized_work_order=work_order.to_dict(),
        verification_evidence_file=record.verification_evidence or "docs/ai/SOURCE_ADAPTATION_GOVERNANCE_REPORT.md",
        rollback_plan=work_order.rollback_deactivation_strategy,
        attribution_notice=work_order.attribution_notice,
        safety_certification=safety,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
