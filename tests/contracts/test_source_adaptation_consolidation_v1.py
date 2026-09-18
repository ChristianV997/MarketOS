"""Focused corrections for source-adaptation consolidation v1."""
from __future__ import annotations

from pathlib import Path

from evaluation.source_governance.registry import AdaptationMode, SourceAdaptationRegistry

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_REGISTRY_PATH = _REPO_ROOT / "data" / "source_adaptation_registry.json"


def test_registry_points_crawl4ai_at_existing_adapter():
    registry = SourceAdaptationRegistry.load_from_file(_REGISTRY_PATH)
    rec = registry.get_record("src-crawl4ai")
    assert rec is not None
    assert rec.marketos_target_authority == "backend.adapters.research.crawl4ai"
    assert rec.adaptation_mode == AdaptationMode.INTEGRATE.value


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
