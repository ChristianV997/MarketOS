"""Focused corrections for source-adaptation consolidation v1."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import re

import pytest

from evaluation.source_governance.consolidation_rules import SYNTHETIC_COMMIT_SHAS
from evaluation.source_governance.registry import (
    AdaptationMode,
    AdaptationWorkOrder,
    SourceAdaptationRegistry,
    WorkOrderRegistry,
)
from evaluation.source_governance.validator import (
    validate_registry,
    validate_source_record,
    validate_source_work_order_correspondence,
    validate_work_order,
)
from scripts.ai.build_source_adaptation_registry import build_and_save


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_REGISTRY_PATH = _REPO_ROOT / "data" / "source_adaptation_registry.json"
_WORK_ORDERS_PATH = _REPO_ROOT / "data" / "source_adaptation_work_orders.json"


def test_canonical_registry_and_work_orders_are_complete_and_one_to_one():
    records = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    work_orders = json.loads(_WORK_ORDERS_PATH.read_text(encoding="utf-8"))

    source_ids = [record["source_id"] for record in records]
    work_order_ids = [order["work_order_id"] for order in work_orders]
    work_order_sources = [order["source_id"] for order in work_orders]

    assert len(records) == len(work_orders) == 29
    assert len(source_ids) == len(set(source_ids))
    assert len(work_order_ids) == len(set(work_order_ids))
    assert len(work_order_sources) == len(set(work_order_sources))
    assert set(source_ids) == set(work_order_sources)
    assert set(work_order_ids) == {
        f"wo-{source_id.removeprefix('src-')}" for source_id in source_ids
    }
    assert len({record["repository_url"] for record in records}) == len(records)
    assert len({order["repository_url"] for order in work_orders}) == len(work_orders)
    assert all(
        re.fullmatch(r"[0-9a-fA-F]{40}", record["commit_sha"])
        for record in records
        if record["source_type"] == "git_repository"
    )
    source_pins = {record["source_id"]: record["commit_sha"] for record in records}
    assert all(
        order["commit_sha"] == source_pins[order["source_id"]]
        and re.fullmatch(r"[0-9a-fA-F]{40}", order["commit_sha"])
        for order in work_orders
    )

    registry = SourceAdaptationRegistry.load_from_file(_REGISTRY_PATH)
    assert validate_registry(registry) == []

    order_registry = WorkOrderRegistry.load_from_file(_WORK_ORDERS_PATH)
    crawl4ai_order = order_registry.get_work_order("wo-crawl4ai")
    assert crawl4ai_order is not None
    assert crawl4ai_order.commit_sha == registry.get_record("src-crawl4ai").commit_sha
    assert crawl4ai_order.target_boundary_authority == "backend.adapters.research.crawl4ai"
    assert crawl4ai_order.marketos_target_module == "backend/adapters/research/crawl4ai.py"
    assert crawl4ai_order.marketos_target_symbol == "Crawl4AIResearchAdapter"

    gpu = registry.get_record("src-higgsfield-gpu-orchestration")
    desktop_bridge = registry.get_record("src-higgsfield-mcp-bridge")
    assert gpu is not None and gpu.adaptation_mode == AdaptationMode.REJECT.value
    assert desktop_bridge is not None
    assert desktop_bridge.adaptation_mode == AdaptationMode.REJECT.value
    assert desktop_bridge.security_surface.desktop_control_risk
    assert desktop_bridge.security_surface.local_ipc

    for source_id in ("src-coderos", "src-gstack", "src-hermes-ecc"):
        reference = registry.get_record(source_id)
        assert reference is not None
        assert reference.adaptation_mode == AdaptationMode.REFERENCE_ONLY.value

    restrictive_licenses = {
        "agpl-3.0", "gpl-3.0", "gpl-2.0", "elv2", "sustainable use license",
        "bsl-1.1", "sspl",
    }
    assert all(
        record["adaptation_mode"] == AdaptationMode.REJECT.value
        for record in records
        if record["license"].strip().lower() in restrictive_licenses
    )


def test_unverified_crawl4ai_pin_stays_deferred():
    registry = SourceAdaptationRegistry.load_from_file(_REGISTRY_PATH)
    rec = registry.get_record("src-crawl4ai")
    assert rec is not None
    assert rec.marketos_target_authority == "backend.adapters.research.crawl4ai"
    assert rec.adaptation_mode == AdaptationMode.DEFER.value
    assert rec.integration_status == "deferred"


def test_unverified_crawl4ai_pin_cannot_be_activated():
    registry = SourceAdaptationRegistry.load_from_file(_REGISTRY_PATH)
    rec = registry.get_record("src-crawl4ai")
    assert rec is not None
    tampered = rec.to_dict()
    tampered["adaptation_mode"] = AdaptationMode.INTEGRATE.value
    tampered["integration_status"] = "accepted"
    errors = validate_source_record(tampered)
    assert any("unverified_source_pin_not_eligible_for_adoption" in error for error in errors)

    work_orders = WorkOrderRegistry.load_from_file(_WORK_ORDERS_PATH)
    work_order = work_orders.get_work_order("wo-crawl4ai")
    assert work_order is not None
    assert any("immutable upstream commit and version tag" in change for change in work_order.required_changes)
    tampered_work_order = work_order.to_dict()
    tampered_work_order["adaptation_mode"] = AdaptationMode.INTEGRATE.value
    work_order_errors = validate_work_order(tampered_work_order)
    assert any(
        "unverified_source_pin_not_eligible_for_adoption" in error
        for error in work_order_errors
    )


def test_stale_scouting_crawl4ai_authority_is_rejected():
    rec = {
        "source_id": "src-crawl4ai-stale",
        "repository_url": "https://github.com/unclecode/crawl4ai",
        "organization": "unclecode",
        "repository_name": "crawl4ai",
        "revision": "b04ed9f3a941a96509272f3bc14be85f5767736a",
        "commit_sha": "b04ed9f3a941a96509272f3bc14be85f5767736a",
        "version_tag": "v0.4.2",
        "source_type": "git_repository",
        "license": "Apache-2.0",
        "license_evidence_url": "https://github.com/unclecode/crawl4ai/blob/main/LICENSE",
        "inspected_paths": ["crawl4ai/async_crawler.py"],
        "dependencies": [],
        "security_surface": {
            "network_access": False,
            "credential_exposure": "none",
            "code_execution": False,
            "local_ipc": False,
            "desktop_control_risk": False,
            "attack_surface_notes": "stale-path fixture",
        },
        "data_network_behavior": {
            "network_mode": "offline_only",
            "outbound_calls_allowed": False,
            "telemetry_mode": "none",
            "data_persistence": "none",
        },
        "adaptation_mode": "integrate",
        "marketos_target_authority": "backend.scouting.crawl4ai_client",
        "expected_benefit": "stale path",
        "compatibility_status": "compatible",
        "integration_status": "accepted",
        "attribution_requirement": "Apache-2.0 notice",
        "rollback_strategy": "delete adapter",
        "owner": "antigravity-source-adaptation-governance-owner",
        "reviewer": "quality-architecture-reviewer",
        "verification_evidence": "tests/contracts/test_source_adaptation_consolidation_v1.py",
        "rejection_reason": None,
        "last_reviewed_at": "2026-09-18T19:00:00Z",
    }
    errs = validate_source_record(rec)
    assert any("stale_target_authority" in e for e in errs)


def test_gpu_orchestration_is_rejected_not_deferred():
    registry = SourceAdaptationRegistry.load_from_file(_REGISTRY_PATH)
    rec = registry.get_record("src-higgsfield-gpu-orchestration")
    assert rec is not None
    assert rec.adaptation_mode == AdaptationMode.REJECT.value
    assert rec.integration_status == "rejected"


def test_no_overlay_registry_or_corrections_file():
    overlay = _REPO_ROOT / "data" / "source_adaptation_corrections_v1.json"
    assert not overlay.exists(), "corrections overlay is not a second authority; apply into canonical registry only"


def test_placeholder_pins_replaced_for_reference_sources():
    registry = SourceAdaptationRegistry.load_from_file(_REGISTRY_PATH)
    coderos = registry.get_record("src-coderos")
    gstack = registry.get_record("src-gstack")
    hermes = registry.get_record("src-hermes-ecc")
    assert coderos is not None and coderos.commit_sha == "b980e90b49ea7c0639094f3060ced5aaf772a571"
    assert gstack is not None and gstack.commit_sha == "a6b3a57512ca6d5c6aa5b68f74f736195021f96e"
    assert hermes is not None
    assert hermes.repository_url == "https://github.com/NousResearch/hermes-agent"
    assert hermes.commit_sha == "027d1a8a6043355b7af53b4c0645336b41372b7b"
    assert hermes.adaptation_mode == AdaptationMode.REFERENCE_ONLY.value


def test_verified_license_evidence_urls_are_immutable():
    registry = SourceAdaptationRegistry.load_from_file(_REGISTRY_PATH)
    verified_pins = {
        "src-hermes-ecc": "027d1a8a6043355b7af53b4c0645336b41372b7b",
        "src-prefect": "c8986edebb2dde3e2a931adbe24d2eaefcb799cb",
    }

    for source_id, commit_sha in verified_pins.items():
        record = registry.get_record(source_id)
        assert record is not None
        assert record.commit_sha == commit_sha
        assert record.license_evidence_url == (
            f"{record.repository_url}/blob/{commit_sha}/LICENSE"
        )


# Tracked-byte lock: GitHub Contents API / PR-body hashes previously claimed
# 55,544 and 61,094 bytes. The actual git blobs on this branch are smaller.
# Pin the working-tree SHA-256 so a truncated rewrite cannot pass JSON-parse-only tests.
_CANONICAL_REGISTRY_BYTES = 54423
_CANONICAL_REGISTRY_SHA256 = "447757bba178226e759e89f0e0803b9cc8ba1d6003c9e08439ffbf845c311bbc"
_CANONICAL_WORK_ORDERS_BYTES = 59693
_CANONICAL_WORK_ORDERS_SHA256 = "e12e9cc190ed457e70c1aa5e41e14ea2c782a29ec48d72e1ebaa3fb4898831dc"
_CANONICAL_STABLE_HASH = "882bb2ee9d604d6ee5af05cb2125ad68a2b1fea56a3f23630150869c56e2e727"

_REQUIRED_VALIDATOR_SYMBOLS = frozenset({
    "validate_registry",
    "validate_source_record",
    "validate_work_order",
    "validate_target_boundary_collisions",
    "validate_source_work_order_correspondence",
    "generate_evidence_bundle",
})
_REQUIRED_CLI_SYMBOLS = frozenset({"run_validation", "main"})
_VALIDATOR_BYTE_FLOOR = 18000
_CLI_BYTE_FLOOR = 8000
_CONSOLIDATION_RULES_BYTE_FLOOR = 400


def test_tracked_registry_bytes_and_raw_sha256_match_git_blobs():
    registry_bytes = _REGISTRY_PATH.read_bytes()
    work_order_bytes = _WORK_ORDERS_PATH.read_bytes()
    # Normalize CRLF to LF for Windows file checkouts so git blob comparison is portable
    norm_registry_bytes = registry_bytes.replace(b"\r\n", b"\n")
    norm_work_order_bytes = work_order_bytes.replace(b"\r\n", b"\n")
    assert len(norm_registry_bytes) == _CANONICAL_REGISTRY_BYTES
    assert len(norm_work_order_bytes) == _CANONICAL_WORK_ORDERS_BYTES
    assert hashlib.sha256(norm_registry_bytes).hexdigest() == _CANONICAL_REGISTRY_SHA256
    assert hashlib.sha256(norm_work_order_bytes).hexdigest() == _CANONICAL_WORK_ORDERS_SHA256
    assert norm_registry_bytes.startswith(b"[\n")
    assert norm_registry_bytes.endswith(b"\n]\n") or norm_registry_bytes.endswith(b"}]\n")
    assert norm_work_order_bytes.startswith(b"[\n")
    assert norm_work_order_bytes.endswith(b"\n]\n") or norm_work_order_bytes.endswith(b"}]\n")
    registry = SourceAdaptationRegistry.load_from_file(_REGISTRY_PATH)
    assert registry.compute_stable_hash() == _CANONICAL_STABLE_HASH


def test_truncated_registry_json_fail_closed(tmp_path: Path):
    raw = _REGISTRY_PATH.read_bytes()
    truncated = raw[: len(raw) // 2]
    assert truncated != raw
    with pytest.raises(json.JSONDecodeError):
        json.loads(truncated.decode("utf-8"))
    truncated_path = tmp_path / "source_adaptation_registry.json"
    truncated_path.write_bytes(truncated)
    with pytest.raises(json.JSONDecodeError):
        SourceAdaptationRegistry.load_from_file(truncated_path)


def test_truncated_work_orders_json_fail_closed(tmp_path: Path):
    raw = _WORK_ORDERS_PATH.read_bytes()
    truncated = raw[: len(raw) // 2]
    with pytest.raises(json.JSONDecodeError):
        json.loads(truncated.decode("utf-8"))
    truncated_path = tmp_path / "source_adaptation_work_orders.json"
    truncated_path.write_bytes(truncated)
    with pytest.raises(json.JSONDecodeError):
        WorkOrderRegistry.load_from_file(truncated_path)


def test_validator_and_cli_are_complete_not_import_stubs():
    validator_path = _REPO_ROOT / "evaluation" / "source_governance" / "validator.py"
    cli_path = _REPO_ROOT / "scripts" / "ai" / "validate_source_adaptation_registry.py"
    rules_path = _REPO_ROOT / "evaluation" / "source_governance" / "consolidation_rules.py"
    assert validator_path.stat().st_size >= _VALIDATOR_BYTE_FLOOR
    assert cli_path.stat().st_size >= _CLI_BYTE_FLOOR
    assert rules_path.stat().st_size >= _CONSOLIDATION_RULES_BYTE_FLOOR

    validator_tree = ast.parse(validator_path.read_text(encoding="utf-8"))
    cli_tree = ast.parse(cli_path.read_text(encoding="utf-8"))
    rules_tree = ast.parse(rules_path.read_text(encoding="utf-8"))

    def fn_names(tree: ast.AST) -> set[str]:
        return {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}

    assert _REQUIRED_VALIDATOR_SYMBOLS <= fn_names(validator_tree)
    assert _REQUIRED_CLI_SYMBOLS <= fn_names(cli_tree)
    assert "extra_record_errors" in fn_names(rules_tree)


def test_unknown_source_id_in_work_order_fail_closed():
    registry = SourceAdaptationRegistry.load_from_file(_REGISTRY_PATH)
    wo_registry = WorkOrderRegistry.load_from_file(_WORK_ORDERS_PATH)
    known = list(wo_registry.work_orders.values())
    ghost = known[0].to_dict()
    ghost["source_id"] = "src-does-not-exist"
    ghost["work_order_id"] = "wo-does-not-exist"
    from evaluation.source_governance.registry import AdaptationWorkOrder

    ghost_wo = AdaptationWorkOrder.from_dict(ghost)
    errs = validate_source_work_order_correspondence(registry, [*known, ghost_wo])
    assert any("unknown_source_id" in e for e in errs)
    assert any("src-does-not-exist" in e for e in errs)

    missing = known[1:]
    missing_errs = validate_source_work_order_correspondence(registry, missing)
    assert any("missing_work_order_for_source" in e for e in missing_errs)

    mode_ghost = known[0].to_dict()
    mode_ghost["adaptation_mode"] = "invented_mode"
    mode_errs = validate_work_order(mode_ghost)
    assert any("unsupported_adaptation_mode" in e for e in mode_errs)


def test_canonical_registry_and_work_orders_correspond_one_to_one():
    registry = SourceAdaptationRegistry.load_from_file(_REGISTRY_PATH)
    wo_registry = WorkOrderRegistry.load_from_file(_WORK_ORDERS_PATH)
    assert validate_source_work_order_correspondence(
        registry, list(wo_registry.work_orders.values())
    ) == []


def test_temporal_license_correction_preserves_fail_closed_rejection():
    """Temporal is correctly documented as MIT but must remain rejected fail-closed on architecture grounds."""
    registry = SourceAdaptationRegistry.load_from_file(_REGISTRY_PATH)
    rec = registry.get_record("src-temporal")
    assert rec is not None
    assert rec.license == "MIT"
    assert rec.compatibility_status == "incompatible_architecture"
    assert rec.adaptation_mode == AdaptationMode.REJECT.value
    assert "single canonical event spine invariant" in rec.rejection_reason

    # Adversarial test: attempting to integrate Temporal into event spine fails closed
    adversarial_rec = rec.to_dict()
    adversarial_rec["adaptation_mode"] = "integrate"
    adversarial_rec["marketos_target_authority"] = "backend.events.spine"
    errs = validate_source_record(adversarial_rec)
    assert any("duplicate_authority_rejected" in e for e in errs)


def test_work_order_adaptation_mode_mismatch_fails_closed():
    """Mismatched adaptation_mode between registry record and work order must fail closed."""
    registry = SourceAdaptationRegistry.load_from_file(_REGISTRY_PATH)
    wo_registry = WorkOrderRegistry.load_from_file(_WORK_ORDERS_PATH)
    known = list(wo_registry.work_orders.values())
    tampered = known[0].to_dict()
    # Change wo-airbyte from reject to integrate
    tampered["adaptation_mode"] = "integrate"
    from evaluation.source_governance.registry import AdaptationWorkOrder

    tampered_wo = AdaptationWorkOrder.from_dict(tampered)
    errs = validate_source_work_order_correspondence(registry, [tampered_wo, *known[1:]])
    assert any("work_order_adaptation_mode_mismatch" in e for e in errs)


# =============================================================================
# ADVERSARIAL REGRESSION SUITE
# Covers: unresolved-pin network egress, canonical-authority usurpation,
# mutation-guard enforcement, synthetic-SHA production-readiness block,
# work-order license mismatch, simultaneous mode+license discrepancy,
# cross-platform byte reproducibility, and deterministic builder idempotency.
# =============================================================================


def test_unresolved_ref_network_egress_fails_closed():
    """Assert that live network egress on an unresolved source (src-crawl4ai)
    is intercepted fail-closed by validate_source_record."""
    registry = SourceAdaptationRegistry.load_from_file(_REGISTRY_PATH)
    crawl4ai_rec = registry.get_record("src-crawl4ai").to_dict()

    crawl4ai_rec["data_network_behavior"]["network_mode"] = "live_network"
    errs = validate_source_record(crawl4ai_rec)
    assert any("unbounded_network_rejected" in e for e in errs), (
        f"Expected unbounded_network_rejected for live_network mode, got: {errs}"
    )

    crawl4ai_rec["data_network_behavior"]["network_mode"] = "unmetered_live"
    errs2 = validate_source_record(crawl4ai_rec)
    assert any("unbounded_network_rejected" in e for e in errs2), (
        f"Expected unbounded_network_rejected for unmetered_live mode, got: {errs2}"
    )


def test_unresolved_ref_cannot_usurp_canonical_authority():
    """Assert that an integrated source cannot displace protected canonical authorities."""
    registry = SourceAdaptationRegistry.load_from_file(_REGISTRY_PATH)
    crawl4ai_rec = registry.get_record("src-crawl4ai").to_dict()

    for protected_auth in (
        "backend.events.spine",
        "backend.finance",
        "evaluation.trustos",
        "evaluation.companyos.approval_ledger",
    ):
        tampered = dict(crawl4ai_rec)
        tampered["adaptation_mode"] = AdaptationMode.INTEGRATE.value
        tampered["marketos_target_authority"] = protected_auth
        errs = validate_source_record(tampered)
        assert any("duplicate_authority_rejected" in e for e in errs), (
            f"Expected duplicate_authority_rejected for {protected_auth}, got: {errs}"
        )


def test_work_order_missing_mutation_guard_fails_closed():
    """Assert that a work order without live-credential/mutation prohibition triggers
    unprotected_change_boundary fail-closed."""
    wo_registry = WorkOrderRegistry.load_from_file(_WORK_ORDERS_PATH)
    crawl4ai_wo = wo_registry.get_work_order("wo-crawl4ai")
    assert crawl4ai_wo is not None

    tampered = crawl4ai_wo.to_dict()
    tampered["prohibited_changes"] = ["do_not_modify_unrelated_files"]
    errs = validate_work_order(tampered)
    assert any("unprotected_change_boundary" in e for e in errs), (
        f"Expected unprotected_change_boundary when mutation guards stripped, got: {errs}"
    )


def test_synthetic_pins_cannot_claim_production_readiness():
    """Assert that sources with synthetic/placeholder commit SHAs fail validate_source_record."""
    registry = SourceAdaptationRegistry.load_from_file(_REGISTRY_PATH)

    for sid in ("src-crawl4ai", "src-higgsfield-cli"):
        base_rec = registry.get_record(sid).to_dict()
        for synth_sha in SYNTHETIC_COMMIT_SHAS:
            tampered = dict(base_rec)
            tampered["commit_sha"] = synth_sha
            tampered["revision"] = synth_sha
            errs = validate_source_record(tampered)
            assert any("synthetic_commit_sha" in e for e in errs), (
                f"Expected synthetic_commit_sha for {synth_sha} in {sid}, got: {errs}"
            )

    records = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    for r in records:
        assert r["commit_sha"] not in SYNTHETIC_COMMIT_SHAS, (
            f"{r['source_id']} contains synthetic commit SHA {r['commit_sha']!r}"
        )


def test_work_order_license_mismatch_fails_closed():
    """Assert that a license discrepancy between a work order and its registry record
    triggers work_order_license_mismatch fail-closed."""
    registry = SourceAdaptationRegistry.load_from_file(_REGISTRY_PATH)
    wo_registry = WorkOrderRegistry.load_from_file(_WORK_ORDERS_PATH)
    known = list(wo_registry.work_orders.values())

    # index 3 == wo-crawl4ai (alphabetical sort of work orders)
    tampered_dict = known[3].to_dict()
    assert tampered_dict["source_id"] == "src-crawl4ai", (
        f"Expected src-crawl4ai at index 3, got: {tampered_dict['source_id']}"
    )
    original_license = tampered_dict["license"]
    tampered_dict["license"] = "MIT"
    tampered_wo = AdaptationWorkOrder.from_dict(tampered_dict)
    work_orders_with_tampered = [
        tampered_wo if wo.work_order_id == "wo-crawl4ai" else wo for wo in known
    ]
    errs = validate_source_work_order_correspondence(registry, work_orders_with_tampered)
    assert any("work_order_license_mismatch" in e for e in errs), (
        f"Expected work_order_license_mismatch, got: {errs}"
    )
    assert any(f"'{original_license}'" in e for e in errs), (
        f"Expected original license {original_license!r} in error message, got: {errs}"
    )

    for sid, rec in registry.records.items():
        wid = f"wo-{sid.removeprefix('src-')}"
        wo = wo_registry.get_work_order(wid)
        assert wo is not None, f"Missing work order {wid}"
        assert wo.license == rec.license, (
            f"License divergence in {wid}: wo '{wo.license}' != rec '{rec.license}'"
        )
        assert wo.adaptation_mode == rec.adaptation_mode, (
            f"Mode divergence in {wid}: wo '{wo.adaptation_mode}' != rec '{rec.adaptation_mode}'"
        )


def test_work_order_simultaneous_mode_and_license_discrepancy():
    """Assert that simultaneous adaptation_mode + license tampering both emit
    distinct fail-closed errors, and that a restrictive license in an active work order
    triggers incompatible_license_in_work_order."""
    registry = SourceAdaptationRegistry.load_from_file(_REGISTRY_PATH)
    wo_registry = WorkOrderRegistry.load_from_file(_WORK_ORDERS_PATH)
    known = list(wo_registry.work_orders.values())

    # index 0 == wo-airbyte
    tampered_dict = known[0].to_dict()
    assert tampered_dict["source_id"] == "src-airbyte"
    tampered_dict["adaptation_mode"] = "integrate"
    tampered_dict["license"] = "MIT"
    tampered_wo = AdaptationWorkOrder.from_dict(tampered_dict)
    errs = validate_source_work_order_correspondence(registry, [tampered_wo, *known[1:]])
    assert any("work_order_adaptation_mode_mismatch" in e for e in errs), (
        f"Expected mode mismatch, got: {errs}"
    )
    assert any("work_order_license_mismatch" in e for e in errs), (
        f"Expected license mismatch, got: {errs}"
    )

    # index 3 == wo-crawl4ai (deferred mode); simulate activation plus a restrictive license.
    crawl4ai_dict = known[3].to_dict()
    assert crawl4ai_dict["adaptation_mode"] == "defer"
    crawl4ai_dict["adaptation_mode"] = "integrate"
    crawl4ai_dict["license"] = "AGPL-3.0"
    wo_errs = validate_work_order(crawl4ai_dict)
    assert any("incompatible_license_in_work_order" in e for e in wo_errs), (
        f"Expected incompatible_license_in_work_order for AGPL-3.0 in active mode, got: {wo_errs}"
    )


def test_builder_lf_line_endings_and_cross_platform_byte_reproducibility(tmp_path):
    """Ensure build_and_save() enforces LF line endings and produces byte-for-byte
    identical output to the tracked canonical files on any OS platform."""

    def _git_blob_sha1(data):
        header = f"blob {len(data)}\0".encode("ascii")
        return hashlib.sha1(header + data, usedforsecurity=False).hexdigest()

    temp_reg = tmp_path / "source_adaptation_registry.json"
    temp_wo = tmp_path / "source_adaptation_work_orders.json"

    rec_count, wo_count = build_and_save(temp_reg, temp_wo)
    assert rec_count == 29
    assert wo_count == 29

    gen_reg_bytes = temp_reg.read_bytes()
    gen_wo_bytes = temp_wo.read_bytes()

    # Strict absence of CRLF and stray CR — must hold even on Windows
    assert b"\r\n" not in gen_reg_bytes, "Builder injected CRLF into registry"
    assert b"\r" not in gen_reg_bytes, "Builder injected stray CR into registry"
    assert b"\r\n" not in gen_wo_bytes, "Builder injected CRLF into work orders"
    assert b"\r" not in gen_wo_bytes, "Builder injected stray CR into work orders"

    # Exact canonical byte length and SHA-256
    assert len(gen_reg_bytes) == _CANONICAL_REGISTRY_BYTES
    assert len(gen_wo_bytes) == _CANONICAL_WORK_ORDERS_BYTES
    assert hashlib.sha256(gen_reg_bytes).hexdigest() == _CANONICAL_REGISTRY_SHA256
    assert hashlib.sha256(gen_wo_bytes).hexdigest() == _CANONICAL_WORK_ORDERS_SHA256

    # Git blob SHA-1 matches LF-normalized working tree
    tracked_reg_lf = _REGISTRY_PATH.read_bytes().replace(b"\r\n", b"\n")
    tracked_wo_lf = _WORK_ORDERS_PATH.read_bytes().replace(b"\r\n", b"\n")
    assert _git_blob_sha1(gen_reg_bytes) == _git_blob_sha1(tracked_reg_lf)
    assert _git_blob_sha1(gen_wo_bytes) == _git_blob_sha1(tracked_wo_lf)

    # Adversarial: CRLF injection alters byte count, SHA-256, and blob hash
    polluted = gen_reg_bytes.replace(b"\n", b"\r\n")
    assert len(polluted) > len(gen_reg_bytes)
    assert hashlib.sha256(polluted).hexdigest() != _CANONICAL_REGISTRY_SHA256
    assert _git_blob_sha1(polluted) != _git_blob_sha1(gen_reg_bytes)


def test_deterministic_builder_output_matches_tracked_files(tmp_path):
    """Verify build_and_save() is bit-for-bit identical to tracked canonical files
    and is idempotent across two consecutive executions."""
    temp_reg = tmp_path / "registry.json"
    temp_wo = tmp_path / "work_orders.json"

    build_and_save(temp_reg, temp_wo)

    gen_reg = temp_reg.read_bytes()
    gen_wo = temp_wo.read_bytes()

    tracked_reg = _REGISTRY_PATH.read_bytes().replace(b"\r\n", b"\n")
    tracked_wo = _WORK_ORDERS_PATH.read_bytes().replace(b"\r\n", b"\n")

    assert gen_reg == tracked_reg, (
        "Builder registry bytes do not match tracked data/source_adaptation_registry.json"
    )
    assert gen_wo == tracked_wo, (
        "Builder work orders bytes do not match tracked data/source_adaptation_work_orders.json"
    )

    reg = SourceAdaptationRegistry.load_from_file(temp_reg)
    wo_reg = WorkOrderRegistry.load_from_file(temp_wo)
    assert len(reg.records) == 29
    assert len(wo_reg.work_orders) == 29
    assert reg.compute_stable_hash() == _CANONICAL_STABLE_HASH

    # Idempotency: second execution must produce byte-identical output
    temp_reg2 = tmp_path / "registry_second.json"
    temp_wo2 = tmp_path / "work_orders_second.json"
    build_and_save(temp_reg2, temp_wo2)
    assert temp_reg2.read_bytes() == gen_reg
    assert temp_wo2.read_bytes() == gen_wo
