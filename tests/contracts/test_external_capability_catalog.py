"""tests/contracts/test_external_capability_catalog.py -- test suite for
MarketOS external capability adoption validator.

Exercises all adoption contract gates:
- valid pinned source
- missing SHA
- malformed SHA
- license missing
- restrictive license
- unverified terms
- credential-bearing metadata
- network-enabled claim
- live activation claim
- rollback missing
- duplicate capability
- incompatible runtime
- stale source
- valid future activation
- rejected live mutation authority
- raw payload URL rejection
- source dossier consistency
- live catalog file validity
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.ai.validate_external_capability_catalog import (
    check_dossier_consistency,
    validate_catalog_data,
)


def get_base_valid_record(cid: str = "valid_candidate") -> dict:
    """Fixture generator for a strictly valid repository candidate."""
    return {
        "capability_id": cid,
        "capability_class": "scouting_extraction",
        "official_source_url": f"https://github.com/example-org/{cid}",
        "repository_or_api_provenance": f"Example Org {cid} Engine",
        "commit_sha": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
        "pinned_release": "v1.0.0",
        "license_or_terms_evidence_url": f"https://github.com/example-org/{cid}/blob/main/LICENSE",
        "license_reuse_disposition": "Permissive Apache-2.0; approved for narrow wrapper",
        "licensing_status": "Apache-2.0",
        "current_availability_state": "offline",
        "activation_state": "planned",
        "cost_assumption": "free_compute",
        "credential_requirement": "none",
        "credential_boundary": "No credentials required or stored",
        "network_mode": "offline",
        "dry_run_manual_fallback": "Returns static fixture data",
        "dry_run_fallback": "Returns static fixture data",
        "input_output_contract": "in_data -> out_data",
        "timeout_retry_policy": "10s timeout",
        "privacy_data_sensitivity_boundary": "Public fixture data only",
        "evidence_class": "fixture_verified",
        "evidence_status": "fixture_verified",
        "marketos_target_module": "backend.adapters.example",
        "integration_mode": "dry-run",
        "activation_blockers": "None",
        "approval_trustos_requirement": "Operator network approval gate",
        "rollback_deactivation_strategy": "Revert to local procedural parsing",
        "duplicate_overlap_disposition": "Canonical engine",
        "compatibility_status": "compatible",
        "owner": "scouting-ops",
        "test_status": "tested",
        "terms_privacy_review": "reviewed",
        "export_safety_status": "safe",
        "vendor_wrap_study": "wrapped",
        "lifecycle": {
            "discovered": True,
            "provenance_reviewed": True,
            "license_reviewed": True,
            "fixture_tested": True,
            "manually_validated": True,
            "integration_tested": True,
            "approved_for_future_activation": True,
            "live_enabled": False,
        },
    }


def test_valid_pinned_source():
    record = get_base_valid_record()
    errors = validate_catalog_data([record])
    assert errors == [], f"Expected no errors, got: {errors}"


def test_missing_sha():
    record = get_base_valid_record()
    record["commit_sha"] = ""
    errors = validate_catalog_data([record])
    assert any("missing_commit_sha" in e for e in errors), f"Expected missing_commit_sha error, got: {errors}"


def test_malformed_sha():
    record = get_base_valid_record()
    # 7-char short sha or tag name should be rejected
    record["commit_sha"] = "a1b2c3d"
    errors = validate_catalog_data([record])
    assert any("malformed_commit_sha" in e for e in errors), f"Expected malformed_commit_sha error, got: {errors}"

    # Non-hex characters
    record["commit_sha"] = "z" * 40
    errors = validate_catalog_data([record])
    assert any("malformed_commit_sha" in e for e in errors), f"Expected malformed_commit_sha error, got: {errors}"


def test_license_missing():
    record = get_base_valid_record()
    record["license_reuse_disposition"] = ""
    errors = validate_catalog_data([record])
    assert any("missing_license" in e for e in errors), f"Expected missing_license error, got: {errors}"

    record2 = get_base_valid_record()
    record2["license_or_terms_evidence_url"] = ""
    errors2 = validate_catalog_data([record2])
    assert any("missing_license" in e for e in errors2), f"Expected missing_license error, got: {errors2}"


def test_restrictive_license():
    # AGPL-3.0 claiming wrapped or integrated
    record = get_base_valid_record()
    record["licensing_status"] = "AGPL-3.0"
    record["license_reuse_disposition"] = "AGPL-3.0 copyleft"
    record["vendor_wrap_study"] = "wrapped"
    errors = validate_catalog_data([record])
    assert any("restrictive_license_rejected" in e for e in errors), f"Expected restrictive_license_rejected, got: {errors}"

    # ELv2 claiming integrate mode
    record2 = get_base_valid_record()
    record2["licensing_status"] = "ELv2"
    record2["license_reuse_disposition"] = "ELv2 non-permissive"
    record2["integration_mode"] = "read-only-live"
    errors2 = validate_catalog_data([record2])
    assert any("restrictive_license_rejected" in e for e in errors2), f"Expected restrictive_license_rejected, got: {errors2}"


def test_unverified_terms():
    record = get_base_valid_record()
    record["terms_privacy_review"] = "unverified"
    errors = validate_catalog_data([record])
    assert any("unverified_terms" in e for e in errors), f"Expected unverified_terms error, got: {errors}"


def test_credential_bearing_metadata():
    record = get_base_valid_record()
    record["credential_boundary"] = "token=ghp_1234567890abcdefghijklmnopqrstuvwxyz"
    errors = validate_catalog_data([record])
    assert any("credential_bearing_metadata" in e for e in errors), f"Expected credential_bearing_metadata, got: {errors}"

    record2 = get_base_valid_record()
    record2["dry_run_manual_fallback"] = "Use sk-live-1234567890abcdef for testing"
    errors2 = validate_catalog_data([record2])
    assert any("credential_bearing_metadata" in e for e in errors2), f"Expected credential_bearing_metadata, got: {errors2}"


def test_network_enabled_claim():
    record = get_base_valid_record()
    record["network_mode"] = "unmetered_live"
    errors = validate_catalog_data([record])
    assert any("network_enabled_claim_rejected" in e for e in errors), f"Expected network_enabled_claim_rejected, got: {errors}"


def test_live_activation_claim():
    # Active availability state without explicit approval
    record = get_base_valid_record()
    record["current_availability_state"] = "active"
    record["explicit_human_approval"] = False
    errors = validate_catalog_data([record])
    assert any("live_activation_claim_rejected" in e for e in errors), f"Expected live_activation_claim_rejected, got: {errors}"

    # live_enabled in lifecycle without approval
    record2 = get_base_valid_record()
    record2["lifecycle"]["live_enabled"] = True
    record2["explicit_human_approval"] = False
    errors2 = validate_catalog_data([record2])
    assert any("live_activation_claim_rejected" in e for e in errors2), f"Expected live_activation_claim_rejected, got: {errors2}"


def test_rollback_missing():
    record = get_base_valid_record()
    record["rollback_deactivation_strategy"] = "   "
    errors = validate_catalog_data([record])
    assert any("missing_rollback_strategy" in e for e in errors), f"Expected missing_rollback_strategy, got: {errors}"

    record2 = get_base_valid_record()
    record2["rollback_deactivation_strategy"] = "placeholder"
    errors2 = validate_catalog_data([record2])
    assert any("missing_rollback_strategy" in e for e in errors2), f"Expected missing_rollback_strategy, got: {errors2}"


def test_duplicate_capability():
    record1 = get_base_valid_record("item_a")
    record2 = get_base_valid_record("item_a")
    errors = validate_catalog_data([record1, record2])
    assert any("duplicate_capability" in e for e in errors), f"Expected duplicate_capability error, got: {errors}"


def test_incompatible_runtime():
    record = get_base_valid_record()
    record["compatibility_status"] = "incompatible_runtime"
    record["integration_mode"] = "integrate"
    record["vendor_wrap_study"] = "wrapped"
    errors = validate_catalog_data([record])
    assert any("incompatible_runtime" in e for e in errors), f"Expected incompatible_runtime error, got: {errors}"


def test_stale_source():
    record = get_base_valid_record()
    record["lifecycle"]["stale_source"] = True
    errors = validate_catalog_data([record])
    assert any("stale_source" in e for e in errors), f"Expected stale_source error, got: {errors}"


def test_valid_future_activation():
    # If approved_for_future_activation is True, but fixture_tested is False -> invalid
    record = get_base_valid_record()
    record["lifecycle"]["fixture_tested"] = False
    record["lifecycle"]["approved_for_future_activation"] = True
    errors = validate_catalog_data([record])
    assert any("invalid_lifecycle_progression" in e for e in errors), f"Expected invalid_lifecycle_progression, got: {errors}"


def test_rejected_live_mutation_authority():
    record = get_base_valid_record()
    record["integration_mode"] = "mutation-capable"
    errors = validate_catalog_data([record])
    assert any("live_mutation_authority_rejected" in e for e in errors), f"Expected live_mutation_authority_rejected, got: {errors}"


def test_raw_payload_url_rejected():
    record = get_base_valid_record()
    record["official_source_url"] = "https://raw.githubusercontent.com/malicious/repo/main/payload.py"
    errors = validate_catalog_data([record])
    assert any("raw_payload_url_rejected" in e for e in errors), f"Expected raw_payload_url_rejected, got: {errors}"


def test_source_dossiers_consistency():
    catalog_path = _REPO_ROOT / "data" / "external_capability_catalog.json"
    dossiers_dir = _REPO_ROOT / "docs" / "ai" / "source_dossiers"
    with open(catalog_path, "r", encoding="utf-8") as f:
        catalog = json.load(f)

    errors = check_dossier_consistency(catalog, dossiers_dir)
    assert errors == [], f"Dossier consistency check failed: {errors}"


def test_main_catalog_file_validity():
    catalog_path = _REPO_ROOT / "data" / "external_capability_catalog.json"
    with open(catalog_path, "r", encoding="utf-8") as f:
        catalog = json.load(f)

    assert len(catalog) >= 31, f"Expected at least 31 capabilities, found {len(catalog)}"
    errors = validate_catalog_data(catalog)
    assert errors == [], f"Main catalog has validation errors: {errors}"
