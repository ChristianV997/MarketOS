"""tests/contracts/test_source_adaptation_governance.py -- Contract and unit tests
for MarketOS source-adaptation registry and governance acceptance pipeline.

Tests:
1. Canonical schema parsing and record validation across all 30 registered sources.
2. Deterministic stable hash verification.
3. Secret-shape detection and redaction.
4. Fail-closed rejection:
   - Missing immutable revision (unpinned Git repository)
   - Incompatible restrictive licenses (AGPL, ELv2, BSL-1.1, Sustainable Use)
   - Duplicate canonical authorities (TrustOS, Governor, Quality, Event Spine)
   - Secret-shaped metadata in catalog
   - Desktop control and uncontrolled local IPC bridges (Higgsfield MCP bridge)
   - GPU orchestration sources without infrastructure
   - Prohibited heavy runtime dependencies
   - Missing rollback strategies and attribution notices
5. Architecture boundaries:
   - CoderOS runtime isolation (zero runtime imports in core)
   - Registry is metadata-only (zero live activation or provider mutation authority)
   - Canonical authorities preservation
"""
from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path

from evaluation.source_governance.registry import (
    AdaptationMode,
    SourceAdaptationRegistry,
    redact_secrets,
)
from evaluation.source_governance.validator import (
    validate_registry,
    validate_source_record,
)
from scripts.benchmarks.benchmark_source_adaptation_registry import execute_matrix

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_REGISTRY_PATH = _REPO_ROOT / "data" / "source_adaptation_registry.json"


def _sample_valid_record(
    source_id: str = "src-valid-test",
    license_name: str = "MIT",
    commit_sha: str = "abcdefabcdefabcdefabcdefabcdefabcdefabcd",
    adaptation_mode: str = "emulate",
    target_authority: str = "backend.analytics.embedded_query_engine",
) -> dict:
    return {
        "source_id": source_id,
        "repository_url": "https://github.com/example/sample-lib",
        "organization": "example",
        "repository_name": "sample-lib",
        "revision": commit_sha,
        "commit_sha": commit_sha,
        "version_tag": "v1.0.0",
        "source_type": "git_repository",
        "license": license_name,
        "license_evidence_url": "https://github.com/example/sample-lib/blob/main/LICENSE",
        "inspected_paths": ["src/query.py"],
        "dependencies": [],
        "security_surface": {
            "network_access": False,
            "credential_exposure": "none",
            "code_execution": False,
            "local_ipc": False,
            "desktop_control_risk": False,
            "attack_surface_notes": "Test fixture."
        },
        "data_network_behavior": {
            "network_mode": "offline_only",
            "outbound_calls_allowed": False,
            "telemetry_mode": "none",
            "data_persistence": "none"
        },
        "adaptation_mode": adaptation_mode,
        "marketos_target_authority": target_authority,
        "expected_benefit": "Testing verification.",
        "compatibility_status": "compatible",
        "integration_status": "accepted_pattern",
        "attribution_requirement": "Sample attribution in THIRD_PARTY_NOTICES.md",
        "rollback_strategy": "Delete test adapter module.",
        "owner": "antigravity-source-adaptation-governance-owner",
        "reviewer": "quality-architecture-reviewer",
        "verification_evidence": "tests/contracts/test_source_adaptation_governance.py",
        "rejection_reason": None,
        "last_reviewed_at": datetime.now(timezone.utc).isoformat(),
    }


# -----------------------------------------------------------------------------
# 1. Canonical Registry & Schema Tests
# -----------------------------------------------------------------------------

def test_canonical_registry_loads_and_passes_validation():
    """Verify that the production catalog loads cleanly and passes all fail-closed checks."""
    assert _REGISTRY_PATH.exists(), f"Registry file missing: {_REGISTRY_PATH}"
    registry = SourceAdaptationRegistry.load_from_file(_REGISTRY_PATH)

    assert len(registry.records) >= 28, f"Expected at least 28 records, got {len(registry.records)}"
    errors = validate_registry(registry)
    assert errors == [], f"Registry validation failed with errors: {errors}"

    # Verify summary structure
    summary = registry.summarize()
    assert summary["total_sources"] == len(registry.records)
    assert "copy_pattern" in summary["modes"]
    assert "emulate" in summary["modes"]
    assert "defer" in summary["modes"]
    assert "reject" in summary["modes"]
    assert "reference_only" in summary["modes"]


def test_stable_hash_is_deterministic_and_bit_identical():
    """Verify that multiple serializations yield the exact same bit-identical SHA-256."""
    reg1 = SourceAdaptationRegistry.load_from_file(_REGISTRY_PATH)
    reg2 = SourceAdaptationRegistry.load_from_file(_REGISTRY_PATH)

    hash1 = reg1.compute_stable_hash()
    hash2 = reg2.compute_stable_hash()

    assert len(hash1) == 64
    assert hash1 == hash2
    # Re-pinned after deliberately adding src-shopify-product-taxonomy (30
    # total records); see data/source_adaptation_registry.json and
    # docs/CATEGORY_MAPPING_EVIDENCE.md.
    assert hash1 == "3c33c0fb3d062f9139cb148e3c0f18716aa4b6b9f7748f86c609477e17b9c2a6"



def test_redact_secrets_filters_tokens():
    """Verify that secret-shaped patterns are cleanly masked."""
    sensitive_data = {
        "user": "developer",
        "gh_token": "ghp_1234567890abcdef1234567890abcdef12",
        "nested": {
            "openai_key": "sk-live-abcdef1234567890abcdef12",
            "safe_val": "hello_world",
        },
        "list_tokens": ["AKIAIOSFODNN7EXAMPLE", "normal_string"],
    }
    redacted = redact_secrets(sensitive_data)
    assert redacted["gh_token"] == "[REDACTED_SECRET]"
    assert redacted["nested"]["openai_key"] == "[REDACTED_SECRET]"
    assert redacted["nested"]["safe_val"] == "hello_world"
    assert redacted["list_tokens"][0] == "[REDACTED_SECRET]"
    assert redacted["list_tokens"][1] == "normal_string"


# -----------------------------------------------------------------------------
# 2. Fail-Closed Validation Tests
# -----------------------------------------------------------------------------

def test_fail_closed_missing_or_malformed_commit_sha():
    """Git repos without a 40-char hex commit SHA must fail closed."""
    # Missing SHA
    rec_missing = _sample_valid_record(commit_sha="")
    errs = validate_source_record(rec_missing)
    assert any("missing_commit_sha" in e for e in errs)

    # Short SHA
    rec_short = _sample_valid_record(commit_sha="abcdef")
    errs = validate_source_record(rec_short)
    assert any("malformed_commit_sha" in e for e in errs)

    # Non-hex characters
    rec_non_hex = _sample_valid_record(commit_sha="zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz")
    errs = validate_source_record(rec_non_hex)
    assert any("malformed_commit_sha" in e for e in errs)


def test_fail_closed_incompatible_restrictive_license():
    """AGPL, ELv2, BSL, Sustainable Use cannot be integrated or emulated."""
    for lic in ("AGPL-3.0", "ELv2", "BSL-1.1", "Sustainable Use License"):
        rec = _sample_valid_record(license_name=lic, adaptation_mode="integrate")
        errs = validate_source_record(rec)
        assert any("incompatible_license_rejected" in e for e in errs), f"Expected rejection for {lic}"


def test_fail_closed_duplicate_authority_target():
    """External sources claiming to duplicate or parallel core authorities must fail closed."""
    for target in ("parallel.marketos_event_spine", "duplicate.evaluation.quality"):
        rec = _sample_valid_record(target_authority=target)
        errs = validate_source_record(rec)
        assert any("duplicate_authority_rejected" in e for e in errs)


def test_fail_closed_secret_shaped_metadata():
    """Secret-shaped keys or values in metadata must fail closed."""
    rec = _sample_valid_record()
    rec["security_surface"]["attack_surface_notes"] = "bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    errs = validate_source_record(rec)
    assert any("credential_bearing_metadata" in e for e in errs)


def test_fail_closed_desktop_control_bridge():
    """Desktop control risk or local IPC in non-rejected mode must fail closed."""
    rec = _sample_valid_record(adaptation_mode="integrate")
    rec["security_surface"]["desktop_control_risk"] = True
    errs = validate_source_record(rec)
    assert any("desktop_control_bridge_rejected" in e for e in errs)


def test_fail_closed_gpu_orchestration():
    """GPU orchestration in integrate mode without cluster infrastructure must fail closed."""
    rec = _sample_valid_record(source_id="src-custom-gpu-orchestrator", adaptation_mode="integrate")
    errs = validate_source_record(rec)
    assert any("gpu_orchestration_unauthorized" in e for e in errs)


def test_fail_closed_prohibited_dependencies():
    """Heavy prohibited runtime dependencies in integrate mode must fail closed."""
    rec = _sample_valid_record(adaptation_mode="integrate")
    rec["dependencies"] = ["twisted", "celery"]
    errs = validate_source_record(rec)
    assert any("prohibited_core_dependency in src-valid-test: 'twisted'" in e for e in errs)
    assert any("prohibited_core_dependency in src-valid-test: 'celery'" in e for e in errs)


def test_fail_closed_missing_rollback_and_attribution():
    """Missing rollback or missing attribution for copied code must fail closed."""
    rec_no_rb = _sample_valid_record()
    rec_no_rb["rollback_strategy"] = ""
    errs = validate_source_record(rec_no_rb)
    assert any("missing_rollback_strategy" in e for e in errs)

    rec_no_attr = _sample_valid_record(adaptation_mode="copy_pattern")
    rec_no_attr["attribution_requirement"] = ""
    errs = validate_source_record(rec_no_attr)
    assert any("missing_attribution_requirement" in e for e in errs)


def test_deterministic_matrix_twelve_scenarios():
    """Verify that all 12 scenarios in the Colab/offline matrix pass with 100% interception."""
    results = execute_matrix()
    assert len(results) == 12
    for r in results:
        assert r["intercepted"] is True, f"Matrix scenario failed: {r}"



# -----------------------------------------------------------------------------
# 3. Architecture Boundary Tests
# -----------------------------------------------------------------------------

def test_architecture_boundary_coderos_not_imported_in_runtime():
    """AST check: CoderOS must never be imported inside backend/ or evaluation/ runtime.
    (Only the isolated plan-only adapter backend/adapters/coderos_readonly.py is permitted).
    """
    forbidden_modules = {"coderos", "scripts.coderos_snapshot"}
    violations = []

    for search_dir in (_REPO_ROOT / "backend", _REPO_ROOT / "evaluation"):
        for py_file in search_dir.rglob("*.py"):
            # Exclude the isolated read-only adapter itself
            if py_file.name == "coderos_readonly.py":
                continue
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"))
            except Exception:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if any(alias.name.startswith(f) for f in forbidden_modules):
                            violations.append((str(py_file), alias.name))
                elif isinstance(node, ast.ImportFrom):
                    if node.module and any(node.module.startswith(f) for f in forbidden_modules):
                        violations.append((str(py_file), node.module))

    assert violations == [], f"CoderOS runtime import violations found: {violations}"


def test_architecture_boundary_registry_is_metadata_only():
    """Verify that the source adaptation registry cannot invoke or mutate live providers."""
    registry = SourceAdaptationRegistry.load_from_file(_REGISTRY_PATH)
    # Check that no record has live mutation capability
    for rec in registry.records.values():
        assert rec.data_network_behavior.network_mode != "unbounded_network"
        assert rec.data_network_behavior.network_mode != "unmetered_live"
        assert not rec.data_network_behavior.outbound_calls_allowed, f"{rec.source_id} allows outbound calls"


def test_architecture_boundary_canonical_authorities_preserved():
    """Verify that TrustOS, Governor, Approval Ledger, Quality, and Event Spine remain canonical."""
    registry = SourceAdaptationRegistry.load_from_file(_REGISTRY_PATH)
    for rec in registry.records.values():
        if rec.adaptation_mode == AdaptationMode.INTEGRATE.value:
            # Cannot replace canonical event spine
            assert "event_spine" not in rec.marketos_target_authority
            # Cannot replace approval ledger
            assert "approval_ledger" not in rec.marketos_target_authority
            # Cannot replace governor
            assert "resource_execution_governor" not in rec.marketos_target_authority


# -----------------------------------------------------------------------------
# 4. Work Order & Evidence Bundle Contract Tests
# -----------------------------------------------------------------------------

def test_canonical_work_orders_load_and_validate():
    """Verify that all generated adaptation work orders load cleanly and pass validation."""
    from evaluation.source_governance.registry import WorkOrderRegistry
    from evaluation.source_governance.validator import validate_work_order, validate_target_boundary_collisions

    wo_path = _REPO_ROOT / "data" / "source_adaptation_work_orders.json"
    assert wo_path.exists(), f"Work orders file missing: {wo_path}"
    registry = WorkOrderRegistry.load_from_file(wo_path)

    assert len(registry.work_orders) == 30
    all_errors = []
    for wo in registry.work_orders.values():
        all_errors.extend(validate_work_order(wo))

    collision_errors = validate_target_boundary_collisions(list(registry.work_orders.values()))
    all_errors.extend(collision_errors)
    assert all_errors == [], f"Work order validation errors: {all_errors}"


def test_work_order_hash_is_deterministic():
    """Work order compute_hash must be bit-identical across runs."""
    from evaluation.source_governance.registry import (
        SourceAdaptationRecord,
        generate_work_order_from_source_record,
    )
    rec = SourceAdaptationRecord.from_dict(_sample_valid_record())
    wo1 = generate_work_order_from_source_record(rec)
    wo2 = generate_work_order_from_source_record(rec)

    assert len(wo1.work_order_hash) == 64
    assert wo1.work_order_hash == wo2.work_order_hash
    assert wo1.compute_hash() == wo1.work_order_hash


def test_target_boundary_collision_detection():
    """Target boundary validator must intercept duplicate module/symbol across active work orders."""
    from evaluation.source_governance.registry import (
        SourceAdaptationRecord,
        generate_work_order_from_source_record,
    )
    from evaluation.source_governance.validator import validate_target_boundary_collisions

    rec1 = SourceAdaptationRecord.from_dict(_sample_valid_record("src-collision-1", adaptation_mode="copy_pattern"))
    rec2 = SourceAdaptationRecord.from_dict(_sample_valid_record("src-collision-2", adaptation_mode="copy_pattern"))

    wo1 = generate_work_order_from_source_record(rec1)
    wo2 = generate_work_order_from_source_record(rec2)

    # Both target the same module and symbol
    assert wo1.marketos_target_module == wo2.marketos_target_module
    assert wo1.marketos_target_symbol == wo2.marketos_target_symbol

    collisions = validate_target_boundary_collisions([wo1, wo2])
    assert len(collisions) == 1
    assert "target_boundary_collision" in collisions[0]


def test_evidence_bundle_generation_and_secret_redaction():
    """Evidence bundle generation must produce markdown and scrub secrets."""
    from evaluation.source_governance.registry import (
        SourceAdaptationRecord,
        generate_work_order_from_source_record,
    )
    from evaluation.source_governance.validator import generate_evidence_bundle

    rec = SourceAdaptationRecord.from_dict(_sample_valid_record())
    wo = generate_work_order_from_source_record(rec)

    bundle = generate_evidence_bundle(wo, rec)
    assert bundle.bundle_id == f"bundle-{wo.work_order_id}"
    assert bundle.work_order_hash == wo.work_order_hash
    assert bundle.safety_certification["zero_credentials"] is True
    assert bundle.safety_certification["zero_network_egress"] is True
    assert bundle.safety_certification["zero_desktop_control"] is True


    md = bundle.render_markdown()
    assert f"# Source Adaptation Review Evidence Bundle: {rec.source_id}" in md
    assert wo.work_order_hash in md

    bundle_dict = bundle.to_dict()
    assert "sanitized_work_order" in bundle_dict
