"""Focused corrections for source-adaptation consolidation v1."""
from __future__ import annotations

import json
from pathlib import Path

from evaluation.source_governance.registry import AdaptationMode, SourceAdaptationRecord
from evaluation.source_governance.consolidation_rules import extra_record_errors

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_REGISTRY_PATH = _REPO_ROOT / "data" / "source_adaptation_registry.json"
_OVERLAY_PATH = _REPO_ROOT / "data" / "source_adaptation_corrections_v1.json"


def _corrected_records() -> dict[str, dict]:
    raw = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    by = {item["source_id"]: dict(item) for item in raw}
    overlay = json.loads(_OVERLAY_PATH.read_text(encoding="utf-8"))
    for item in overlay["corrections"]:
        sid = item["source_id"]
        by[sid].update({k: v for k, v in item.items() if k != "source_id"})
    return by


def test_registry_points_crawl4ai_at_existing_adapter():
    rec = _corrected_records()["src-crawl4ai"]
    assert rec["marketos_target_authority"] == "backend.adapters.research.crawl4ai"
    assert rec["adaptation_mode"] == AdaptationMode.INTEGRATE.value
    assert extra_record_errors(rec) == []


def test_stale_scouting_path_is_flagged():
    rec = {"source_id": "src-stale", "marketos_target_authority": "backend.scouting.crawl4ai_client", "adaptation_mode": "integrate"}
    errs = extra_record_errors(rec)
    assert any("stale_target_authority" in e for e in errs)


def test_gpu_orchestration_is_rejected_not_deferred():
    rec = _corrected_records()["src-higgsfield-gpu-orchestration"]
    assert rec["adaptation_mode"] == AdaptationMode.REJECT.value
    assert rec["integration_status"] == "rejected"
    parsed = SourceAdaptationRecord.from_dict(rec)
    assert parsed.adaptation_mode == AdaptationMode.REJECT.value


def test_placeholder_pins_replaced_for_reference_sources():
    recs = _corrected_records()
    assert recs["src-coderos"]["commit_sha"] == "b980e90b49ea7c0639094f3060ced5aaf772a571"
    assert recs["src-gstack"]["commit_sha"] == "a6b3a57512ca6d5c6aa5b68f74f736195021f96e"
    hermes = recs["src-hermes-ecc"]
    assert hermes["repository_url"] == "https://github.com/NousResearch/hermes-agent"
    assert hermes["commit_sha"] == "027d1a8a6043355b7af53b4c0645336b41372b7b"
    assert hermes["adaptation_mode"] == AdaptationMode.REFERENCE_ONLY.value
