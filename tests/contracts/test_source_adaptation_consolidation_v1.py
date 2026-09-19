"""Focused corrections for source-adaptation consolidation v1."""
from __future__ import annotations

import json
from pathlib import Path
import re

from evaluation.source_governance.registry import (
    AdaptationMode,
    SourceAdaptationRegistry,
    WorkOrderRegistry,
)
from evaluation.source_governance.validator import validate_registry, validate_source_record


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


def test_registry_points_crawl4ai_at_existing_adapter():
    registry = SourceAdaptationRegistry.load_from_file(_REGISTRY_PATH)
    rec = registry.get_record("src-crawl4ai")
    assert rec is not None
    assert rec.marketos_target_authority == "backend.adapters.research.crawl4ai"
    assert rec.adaptation_mode == AdaptationMode.INTEGRATE.value


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
