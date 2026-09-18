"""scripts/ai/validate_external_capability_catalog.py -- machine validation logic
for MarketOS external capability adoption registry.

Enforces strict source-adoption rules:
- Full 40-character commit SHAs (xAI/Grok plugin pinning model)
- License verification & restrictive license rejection (AGPL, ELv2, Sustainable Use License)
- Credential boundary enforcement (rejects secret-shaped metadata)
- Network safety (rejects unbounded/unmetered live claims)
- Rollback deactivation strategy requirement
- Lifecycle progression integrity
- Dossier consistency
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

_HEX_40_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_SECRET_KEY_NAMES = frozenset({
    "api_key", "apikey", "access_token", "authorization", "auth_token",
    "password", "private_key", "secret", "secret_key", "token", "credential",
    "cookie", "cookies",
})
_SECRET_SHAPED_VALUE = re.compile(
    r"(?is)("
    r"-----begin (?:rsa |ec |dsa |openssh )?private key-----"
    r"|ghp_[A-Za-z0-9_]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|sk-(?:live|test)?-?[A-Za-z0-9]{16,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|bearer [A-Za-z0-9._-]{10,}"
    r")"
)

RESTRICTIVE_LICENSES = frozenset({
    "agpl-3.0", "agpl", "gpl-3.0", "gpl", "elv2", "elastic-license-2.0",
    "sustainable use license", "bsl-1.1", "sspl", "proprietary copyleft"
})

REQUIRED_BASE_KEYS = frozenset({
    "capability_id", "capability_class", "official_source_url", "repository_or_api_provenance",
    "license_or_terms_evidence_url", "license_reuse_disposition", "current_availability_state",
    "cost_assumption", "credential_requirement", "dry_run_manual_fallback",
    "input_output_contract", "timeout_retry_policy", "privacy_data_sensitivity_boundary",
    "evidence_class", "marketos_target_module", "integration_mode", "activation_blockers",
    "approval_trustos_requirement", "rollback_deactivation_strategy", "duplicate_overlap_disposition"
})

VALID_CLASSES = frozenset({
    "market_intelligence", "demand_intelligence", "supplier_intelligence",
    "creative_intelligence", "channel_intelligence", "data_import",
    "social_attention_evidence", "scouting_extraction", "embedded_analytics",
    "provenance_observability", "governance_policy", "data_quality",
    "headless_commerce", "workflow_automation"
})

VALID_INTEGRATION_MODES = frozenset({
    "fixture", "manual-import", "dry-run", "read-only-live", "mutation-capable"
})


def _contains_credentials(val: Any) -> bool:
    """Recursively search for credentials or secret-shaped values."""
    if isinstance(val, dict):
        for k, v in val.items():
            kl = str(k).lower().replace("-", "_")
            if kl in _SECRET_KEY_NAMES and str(v).strip().lower() not in {"none", "n/a", "isolated", "", "true", "false"}:
                # If key name is secret-like and has an actual secret value
                if _SECRET_SHAPED_VALUE.search(str(v)) or len(str(v).strip()) > 15:
                    return True
            if _contains_credentials(v):
                return True
    elif isinstance(val, list):
        for item in val:
            if _contains_credentials(item):
                return True
    elif isinstance(val, str):
        if _SECRET_SHAPED_VALUE.search(val):
            return True
    return False


def validate_capability_record(item: Dict[str, Any], seen_ids: Set[str], prev_cid: Optional[str]) -> List[str]:
    """Validate a single capability catalog record."""
    errors: List[str] = []
    cid = item.get("capability_id", "<UNKNOWN>")

    # 1. Required keys check
    missing_keys = REQUIRED_BASE_KEYS - set(item.keys())
    if missing_keys:
        errors.append(f"Record {cid} missing keys: {sorted(missing_keys)}")
        return errors

    # 2. Duplicate capability ID
    if cid in seen_ids:
        errors.append(f"duplicate_capability: Duplicate capability_id: {cid}")
    seen_ids.add(cid)

    # 3. Deterministic alphabetical ordering
    if prev_cid and cid < prev_cid:
        errors.append(f"nondeterministic_ordering: {cid} comes after {prev_cid}")

    # 4. Capability class validity
    if item.get("capability_class") not in VALID_CLASSES:
        errors.append(f"conflicting_capability_class in {cid}: {item.get('capability_class')}")

    # 5. Integration mode validity
    imode = item.get("integration_mode")
    if imode not in VALID_INTEGRATION_MODES:
        errors.append(f"invalid_integration_mode in {cid}: {imode}")

    # 6. Live mutation authority rejected
    if imode == "mutation-capable":
        errors.append(f"live_mutation_authority_rejected: {cid} claims mutation-capable integration mode")

    # 7. Rollback deactivation strategy requirement
    rollback = str(item.get("rollback_deactivation_strategy", "")).strip()
    if not rollback or rollback.lower() in {"none", "n/a", "placeholder", "tbd"}:
        errors.append(f"missing_rollback_strategy in {cid}")

    # 8. Provenance and source URL validation
    provenance = str(item.get("repository_or_api_provenance", "")).strip()
    if not provenance:
        errors.append(f"missing_provenance in {cid}")

    source_url = str(item.get("official_source_url", "")).strip()
    if not source_url or "placeholder" in source_url:
        errors.append(f"placeholder_source_url in {cid}")

    # Raw payload URL rejection
    if "raw.githubusercontent.com" in source_url or "raw_payload" in source_url:
        errors.append(f"raw_payload_url_rejected in {cid}: {source_url}")

    # 9. Pinned Commit SHA validation (Grok/xAI pinning model)
    is_repo_source = any(host in source_url.lower() for host in ("github.com", "gitlab.com"))
    commit_sha = item.get("commit_sha")
    if is_repo_source:
        if not commit_sha or str(commit_sha).strip() == "":
            errors.append(f"missing_commit_sha in {cid}: repository source must provide pinned commit_sha")
        elif not _HEX_40_RE.match(str(commit_sha).strip()):
            errors.append(f"malformed_commit_sha in {cid}: commit_sha must be 40-character hex string, got '{commit_sha}'")

    # 10. License evidence & restrictive license rejection
    license_disp = str(item.get("license_reuse_disposition", "")).strip()
    license_url = str(item.get("license_or_terms_evidence_url", "")).strip()
    licensing_status = str(item.get("licensing_status", "")).strip()

    if not license_disp or not license_url:
        errors.append(f"missing_license in {cid}: license evidence or disposition missing")

    # Check restrictive license claims
    lic_lower = (license_disp + " " + licensing_status).lower()
    is_restrictive = any(rl in lic_lower for rl in RESTRICTIVE_LICENSES)
    vendor_study = str(item.get("vendor_wrap_study", "")).lower()

    if is_restrictive:
        if imode in ("integrate", "read-only-live", "mutation-capable") or vendor_study in ("vendored", "wrapped"):
            errors.append(f"restrictive_license_rejected: {cid} has restrictive license ({licensing_status}) and cannot be integrated or wrapped")

    # 11. Credential-bearing metadata rejection
    if _contains_credentials(item):
        errors.append(f"credential_bearing_metadata in {cid}")

    # Credential requirement without privacy boundary
    creds = str(item.get("credential_requirement", "")).lower()
    privacy_boundary = str(item.get("privacy_data_sensitivity_boundary", "")).strip()
    if creds not in ("none", "n/a", "") and not privacy_boundary:
        errors.append(f"credential_without_privacy_boundary in {cid}")

    # 12. Network safety & unbounded network behavior rejection
    net_mode = str(item.get("network_mode", "")).lower()
    if net_mode in ("unbounded_network", "unmetered_live", "live_network"):
        errors.append(f"network_enabled_claim_rejected in {cid}: unmetered/unbounded live network claim is prohibited")

    # 13. Live activation claim without explicit approval
    curr_avail = str(item.get("current_availability_state", "")).lower()
    lifecycle = item.get("lifecycle")
    live_enabled = False
    if isinstance(lifecycle, dict):
        live_enabled = bool(lifecycle.get("live_enabled", False))

    if curr_avail == "active" or live_enabled:
        if not (isinstance(lifecycle, dict) and lifecycle.get("approved_for_future_activation")):
            errors.append(f"live_activation_claim_rejected in {cid}: active capability is not approved_for_future_activation")
        if not item.get("explicit_human_approval", False):
            errors.append(f"live_activation_claim_rejected in {cid}: live activation requires explicit_human_approval")

    # 14. Incompatible runtime
    compat = str(item.get("compatibility_status", "")).lower()
    if compat == "incompatible_runtime" and imode in ("integrate", "read-only-live") and vendor_study in ("vendored", "wrapped"):
        errors.append(f"incompatible_runtime in {cid}: cannot integrate runtime marked incompatible_runtime")

    # 15. Stale source rejection
    if isinstance(lifecycle, dict) and lifecycle.get("stale_source", False):
        errors.append(f"stale_source in {cid}: candidate marked as stale source")

    # 16. Terms / privacy review
    terms_rev = str(item.get("terms_privacy_review", "")).lower()
    if terms_rev in ("unverified", "rejected") and (imode in ("integrate", "read-only-live") or (isinstance(lifecycle, dict) and lifecycle.get("approved_for_future_activation"))):
        errors.append(f"unverified_terms in {cid}: unverified or rejected terms review")

    # 17. Lifecycle progression integrity
    if not isinstance(lifecycle, dict):
        errors.append(f"missing_lifecycle in {cid}")
    else:
        expected_stages = [
            "discovered", "provenance_reviewed", "license_reviewed",
            "fixture_tested", "manually_validated", "integration_tested",
            "approved_for_future_activation"
        ]
        missing_stages = set(expected_stages) - set(lifecycle.keys())
        if missing_stages:
            errors.append(f"missing_lifecycle_stages in {cid}: {sorted(missing_stages)}")
        else:
            # If approved_for_future_activation is True, all previous must be True
            if lifecycle.get("approved_for_future_activation"):
                for stage in expected_stages[:-1]:
                    if not lifecycle.get(stage):
                        errors.append(f"invalid_lifecycle_progression in {cid}: '{stage}' must be true before approved_for_future_activation")

    return errors


def validate_catalog_data(catalog: List[Dict[str, Any]]) -> List[str]:
    """Validate full capability catalog list."""
    if not isinstance(catalog, list):
        return ["catalog_must_be_list"]

    all_errors: List[str] = []
    seen_ids: Set[str] = set()
    prev_cid: Optional[str] = None

    for item in catalog:
        errs = validate_capability_record(item, seen_ids, prev_cid)
        all_errors.extend(errs)
        prev_cid = item.get("capability_id")

    return all_errors


def check_dossier_consistency(catalog: List[Dict[str, Any]], dossiers_dir: Path) -> List[str]:
    """Ensure every repository candidate has a matching dossier."""
    errors: List[str] = []
    if not dossiers_dir.exists():
        return [f"dossiers_dir_missing: {dossiers_dir}"]

    dossier_files = {p.stem: p for p in dossiers_dir.glob("*.md") if p.stem != "INDEX"}

    for item in catalog:
        cid = item.get("capability_id", "")
        source_url = item.get("official_source_url", "")
        if any(host in source_url.lower() for host in ("github.com", "gitlab.com")):
            if cid not in dossier_files:
                errors.append(f"missing_dossier: No dossier found for repository candidate '{cid}'")
            else:
                # Check that commit SHA in dossier matches catalog
                dossier_text = dossier_files[cid].read_text(encoding="utf-8")
                commit_sha = item.get("commit_sha", "")
                if commit_sha and commit_sha != "0000000000000000000000000000000000000000":
                    if commit_sha not in dossier_text:
                        errors.append(f"dossier_sha_mismatch: Dossier for '{cid}' does not contain pinned commit_sha '{commit_sha}'")

    return errors


def validate_catalog(path: str, dossiers_dir: Optional[str] = None) -> bool:
    """Validate catalog file and optional dossiers directory."""
    cat_path = Path(path).resolve()
    if not cat_path.exists():
        print(f"Error: Catalog not found at {cat_path}")
        return False

    with open(cat_path, "r", encoding="utf-8") as f:
        catalog = json.load(f)

    errors = validate_catalog_data(catalog)

    if dossiers_dir:
        d_dir = Path(dossiers_dir).resolve()
        d_errors = check_dossier_consistency(catalog, d_dir)
        errors.extend(d_errors)

    if errors:
        for err in errors:
            print(f"Validation Error: {err}")
        return False

    print(f"Catalog validation passed successfully ({len(catalog)} capabilities verified).")
    return True


if __name__ == "__main__":
    catalog_arg = "data/external_capability_catalog.json"
    dossiers_arg = "docs/ai/source_dossiers"
    if len(sys.argv) > 1:
        catalog_arg = sys.argv[1]
    if len(sys.argv) > 2:
        dossiers_arg = sys.argv[2]

    success = validate_catalog(catalog_arg, dossiers_arg)
    sys.exit(0 if success else 1)
