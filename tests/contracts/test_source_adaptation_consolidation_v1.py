"""Focused corrections for source-adaptation consolidation v1."""
from __future__ import annotations

from pathlib import Path

from evaluation.source_governance.registry import AdaptationMode, SourceAdaptationRegistry
from evaluation.source_governance.validator import validate_source_record


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_REGISTRY_PATH = _REPO_ROOT / "data" / "source_adaptation_registry.json"


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
