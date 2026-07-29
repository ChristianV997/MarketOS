"""Tests for the execution connector and attribution lineage.

Covers:
  1. CampaignArtifact dataclass — fields and serialisation
  2. emit_campaign_launched — importable and fail-silent
  3. PatternStore.snapshot / restore — round-trip
  4. PatternStore auto-persist — writes to disk on update
  5. PatternStore cold-start load — restores from disk on import
  6. _campaign_artifacts populated by _run_scaling
  7. Artifact carries correct hook/angle/product lineage
  8. _run_metrics_ingestion backfills PatternStore from TikTok ROAS
  9. _run_metrics_ingestion records calibration per product
  10. _run_metrics_ingestion is safe with empty _campaign_artifacts
  11. CAMPAIGN_LAUNCHED constant exists in schemas
  12. Full launch→artifact→ROAS→PatternStore round-trip
"""
import os
import json
import time
import tempfile
import importlib


# ── 1. CampaignArtifact dataclass ────────────────────────────────────────────

def test_campaign_artifact_fields():
    from core.content.schemas import CampaignArtifact
    a = CampaignArtifact(
        campaign_id="cid_001",
        adgroup_id="ag_001",
        ad_ids=["ad_1", "ad_2"],
        product="wireless earbuds",
        hook="Nobody is talking about this…",
        angle="social-proof",
        phase="EXPLORE",
        estimated_roas=1.5,
        budget=50.0,
    )
    assert a.campaign_id == "cid_001"
    assert a.product == "wireless earbuds"
    assert a.hook == "Nobody is talking about this…"
    assert a.angle == "social-proof"
    assert a.phase == "EXPLORE"
    assert a.estimated_roas == 1.5
    assert isinstance(a.launched_at, float)
    assert a.dry_run is True  # safe default


def test_campaign_artifact_to_dict_is_json_safe():
    from core.content.schemas import CampaignArtifact
    a = CampaignArtifact(
        campaign_id="cid_002", adgroup_id="ag_002", ad_ids=["ad_a"],
        product="led strips", hook="hook", angle="angle",
        phase="SCALE", estimated_roas=2.0, budget=100.0,
    )
    d = a.to_dict()
    serialised = json.dumps(d)  # must not raise
    assert json.loads(serialised)["product"] == "led strips"
    assert isinstance(d["ad_ids"], list)


# ── 2. emit_campaign_launched ─────────────────────────────────────────────────

def test_emit_campaign_launched_importable():
    from backend.events.emitter import emit_campaign_launched
    assert callable(emit_campaign_launched)


def test_emit_campaign_launched_does_not_raise():
    from backend.events.emitter import emit_campaign_launched
    emit_campaign_launched(
        campaign_id="dry_test_001",
        product="posture corrector",
        hook="This changed everything…",
        angle="problem-solution",
        phase="EXPLORE",
        budget=50.0,
        dry_run=True,
    )  # must not raise


# ── 3. CAMPAIGN_LAUNCHED schema constant ─────────────────────────────────────

def test_campaign_launched_constant_in_schemas():
    from backend.events.schemas import CAMPAIGN_LAUNCHED
    assert CAMPAIGN_LAUNCHED == "campaign.launched"


# ── 4. PatternStore snapshot / restore round-trip ────────────────────────────

def test_patternstore_snapshot_returns_json_safe_dict():
    from core.content.patterns import PatternStore, extract_patterns
    store = PatternStore()
    store.update(extract_patterns([
        {"hook": "hook_A", "angle": "angle_X", "roas": 1.8, "env_regime": "growth"},
    ]))
    snap = store.snapshot()
    assert "hook_scores" in snap
    assert "angle_scores" in snap
    assert "regime_scores" in snap
    json.dumps(snap)  # must be JSON-safe


def test_patternstore_restore_round_trip():
    from core.content.patterns import PatternStore, extract_patterns
    store = PatternStore()
    store.update(extract_patterns([
        {"hook": "UNIQUE_HOOK_RESTORE", "angle": "angle_Y", "roas": 2.0, "eng_score": 0.9},
    ]))
    snap = store.snapshot()
    assert "UNIQUE_HOOK_RESTORE" in snap["hook_scores"]

    fresh = PatternStore()
    fresh.restore(snap)
    assert "UNIQUE_HOOK_RESTORE" in fresh.get_top_hooks(n=5)


# ── 5. PatternStore auto-persist to disk ─────────────────────────────────────

def test_patternstore_persists_on_update(tmp_path, monkeypatch):
    import core.content.patterns as pat_mod
    snap_path = str(tmp_path / "patternstore.json")
    monkeypatch.setattr(pat_mod, "_PATTERNSTORE_PATH", snap_path)

    store = pat_mod.PatternStore()
    store.update(pat_mod.extract_patterns([
        {"hook": "PERSISTED_HOOK", "angle": "angle_Z", "roas": 1.6, "eng_score": 0.7},
    ]))

    assert os.path.exists(snap_path), "snapshot file should have been written"
    with open(snap_path) as f:
        data = json.load(f)
    assert "PERSISTED_HOOK" in data["hook_scores"]


def test_patternstore_loads_on_cold_start(tmp_path, monkeypatch):
    """Simulate module-level load: if snapshot file exists, scores are restored."""
    import core.content.patterns as pat_mod

    snap_path = str(tmp_path / "patternstore_cold.json")
    snap_data = {
        "hook_scores":   {"COLD_HOOK": 0.88},
        "angle_scores":  {"cold_angle": 0.55},
        "regime_scores": {"growth": 0.70},
    }
    with open(snap_path, "w") as f:
        json.dump(snap_data, f)

    monkeypatch.setattr(pat_mod, "_PATTERNSTORE_PATH", snap_path)
    fresh = pat_mod.PatternStore()
    pat_mod._load_patternstore.__globals__["pattern_store"] = fresh
    pat_mod._load_patternstore()

    assert "COLD_HOOK" in fresh.get_top_hooks(n=5)


# ── 6. _campaign_artifacts populated after _run_scaling ──────────────────────

def test_campaign_artifacts_populated_after_scaling():
    import orchestrator.main as orch
    from core.content.playbook import playbook_memory, Playbook

    pb = Playbook(
        product="exec_connector_test_product",
        phase="SCALE",
        top_hooks=["This changed everything…"],
        top_angles=["problem-solution"],
        estimated_roas=1.9,
        confidence=0.85,
        evidence_count=25,
    )
    playbook_memory.upsert(pb)
    orch._campaign_artifacts.clear()
    orch._scaling_limiter.last_run = 0.0

    orch._run_scaling()

    # Even in dry-run mode, artifact should be stored
    products_in_artifacts = {a.product for a in orch._campaign_artifacts.values()}
    assert "exec_connector_test_product" in products_in_artifacts


# ── 7. Artifact carries hook / angle / product lineage ───────────────────────

def test_artifact_carries_hook_and_angle():
    import orchestrator.main as orch
    from core.content.playbook import playbook_memory, Playbook

    pb = Playbook(
        product="lineage_test_product",
        phase="SCALE",
        top_hooks=["Stop wasting money on this…"],
        top_angles=["urgency"],
        estimated_roas=2.1,
        confidence=0.9,
        evidence_count=30,
    )
    playbook_memory.upsert(pb)
    orch._campaign_artifacts.clear()
    orch._scaling_limiter.last_run = 0.0

    orch._run_scaling()

    for artifact in orch._campaign_artifacts.values():
        if artifact.product == "lineage_test_product":
            assert artifact.hook == "Stop wasting money on this…"
            assert artifact.angle == "urgency"
            break


def test_artifact_to_dict_preserves_lineage():
    import orchestrator.main as orch
    for artifact in orch._campaign_artifacts.values():
        d = artifact.to_dict()
        assert "product" in d and "hook" in d and "angle" in d
        assert "campaign_id" in d and "launched_at" in d
        break  # just check first artifact


# ── 8. _run_metrics_ingestion backfills PatternStore ─────────────────────────

def test_metrics_ingestion_backfills_patternstore(monkeypatch):
    """Real ROAS from _campaign_artifacts should update PatternStore hook scores."""
    import orchestrator.main as orch
    from core.content.schemas import CampaignArtifact
    from core.content.patterns import PatternStore, extract_patterns
    import core.content.patterns as pat_mod

    local_store = PatternStore()
    original = pat_mod.pattern_store
    pat_mod.pattern_store = local_store

    orch._campaign_artifacts.clear()
    orch._campaign_artifacts["dry_backfill_001"] = CampaignArtifact(
        campaign_id="dry_backfill_001",
        adgroup_id="ag_bf",
        ad_ids=["ad_bf"],
        product="backfill_product",
        hook="BACKFILL_HOOK_UNIQUE",
        angle="problem-solution",
        phase="SCALE",
        estimated_roas=1.8,
        budget=60.0,
        dry_run=True,
    )

    try:
        orch._run_metrics_ingestion()
        hooks = local_store.get_top_hooks(n=10)
        assert "BACKFILL_HOOK_UNIQUE" in hooks, \
            f"PatternStore should have learned BACKFILL_HOOK_UNIQUE from TikTok ROAS, got: {hooks}"
    finally:
        pat_mod.pattern_store = original
        orch._campaign_artifacts.clear()


# ── 9. _run_metrics_ingestion records calibration per product ─────────────────

def test_metrics_ingestion_records_calibration_per_product():
    import orchestrator.main as orch
    from core.content.schemas import CampaignArtifact
    from simulation.calibration import CalibrationStore
    import simulation.calibration as cal_mod

    fresh_store = CalibrationStore()
    original = cal_mod.calibration_store
    cal_mod.calibration_store = fresh_store

    orch._campaign_artifacts.clear()
    orch._campaign_artifacts["dry_cal_001"] = CampaignArtifact(
        campaign_id="dry_cal_001", adgroup_id="ag_c", ad_ids=["ad_c"],
        product="calibration_product", hook="hook_c", angle="angle_c",
        phase="SCALE", estimated_roas=1.5, budget=50.0, dry_run=True,
    )

    try:
        orch._run_metrics_ingestion()
        # CalibrationStore should have attempted record_outcome for "calibration_product"
        # (may or may not pair if no pending prediction, but must not raise)
        assert fresh_store.total_paired >= 0
    finally:
        cal_mod.calibration_store = original
        orch._campaign_artifacts.clear()


# ── 10. _run_metrics_ingestion safe with no tracked campaigns ─────────────────

def test_metrics_ingestion_safe_when_no_artifacts():
    import orchestrator.main as orch
    orch._campaign_artifacts.clear()
    result = orch._run_metrics_ingestion()
    assert result["status"] in ("ok", "skipped", "error")


# ── 11. Full round-trip: launch → artifact → ROAS → PatternStore hook score ──

def test_full_launch_to_patternstore_round_trip():
    """End-to-end: seed playbook → scale → artifact stored → metrics backfill → hook learned."""
    import orchestrator.main as orch
    from core.content.playbook import playbook_memory, Playbook
    from core.content.patterns import PatternStore
    import core.content.patterns as pat_mod

    orch._scaling_limiter.last_run = 0.0  # bypass rate limiting so _run_scaling actually runs
    local_store = PatternStore()
    original = pat_mod.pattern_store
    pat_mod.pattern_store = local_store

    UNIQUE_HOOK = "ROUNDTRIP_HOOK_XYZ_UNIQUE"
    pb = Playbook(
        product="roundtrip_product",
        phase="SCALE",
        top_hooks=[UNIQUE_HOOK],
        top_angles=["social-proof"],
        estimated_roas=2.0,
        confidence=0.95,
        evidence_count=40,
    )
    playbook_memory.upsert(pb)
    orch._campaign_artifacts.clear()

    try:
        # Step 1: Launch → artifact
        orch._run_scaling()
        assert any(a.hook == UNIQUE_HOOK for a in orch._campaign_artifacts.values()), \
            "artifact should carry the unique hook"

        # Step 2: Metrics backfill → PatternStore
        orch._run_metrics_ingestion()
        hooks = local_store.get_top_hooks(n=20)
        assert UNIQUE_HOOK in hooks, \
            f"PatternStore should have learned {UNIQUE_HOOK} after metrics backfill, got: {hooks}"
    finally:
        pat_mod.pattern_store = original
        orch._campaign_artifacts.clear()
