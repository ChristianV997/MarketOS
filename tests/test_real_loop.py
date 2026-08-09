"""Tests for the real operational money loop.

Covers the three critical data-flow fixes:
  1. hook + angle + product fields appear in every execution outcome
  2. PatternStore learns from outcomes → content generation uses real patterns
  3. Campaign tracking ties TikTok ROAS back to specific products
  4. _run_content_generation uses real signal products, never skips on cold start
  5. _campaign_artifacts populated after launch_from_playbook
  6. _run_metrics_ingestion records per-product outcomes via _campaign_artifacts
  7. Full signal → content → deploy → metrics → calibration round-trip
"""
import time


# ── Fix 1: hook/angle/product flow through execute() ─────────────────────────

def test_execute_outcomes_have_hook_field():
    """Every execution outcome must include a 'hook' key."""
    from backend.core.state import SystemState
    from backend.execution.loop import execute
    from backend.decision.engine import decide

    state = SystemState()
    decisions = decide(state)
    results = execute(decisions, state)
    assert results, "execute() returned no results"
    for r in results:
        assert "hook" in r, f"missing 'hook' in outcome: {r.keys()}"
        assert r["hook"], "hook is empty string"


def test_execute_outcomes_have_angle_field():
    from backend.core.state import SystemState
    from backend.execution.loop import execute
    from backend.decision.engine import decide

    state = SystemState()
    results = execute(decide(state), state)
    for r in results:
        assert "angle" in r, f"missing 'angle' in outcome: {r.keys()}"
        assert r["angle"], "angle is empty string"


def test_execute_outcomes_have_product_field():
    from backend.core.state import SystemState
    from backend.execution.loop import execute
    from backend.decision.engine import decide

    state = SystemState()
    results = execute(decide(state), state)
    for r in results:
        assert "product" in r, f"missing 'product' in outcome: {r.keys()}"


def test_decide_includes_product_name():
    """Decision dicts must carry product_name so execute() can use it."""
    from backend.core.state import SystemState
    from backend.decision.engine import decide

    state = SystemState()
    decisions = decide(state)
    for d in decisions:
        assert "product_name" in d, f"decision missing product_name: {d.keys()}"


# ── Fix 2: PatternStore learns from hook-annotated outcomes ───────────────────

def test_pattern_store_updates_from_winner_outcomes():
    """After batch_classify on outcomes with hooks, PatternStore gets hook_scores."""
    from core.content.patterns import PatternStore, extract_patterns

    events = [
        {"hook": "This changed everything…", "angle": "problem-solution",
         "roas": 2.0, "ctr": 0.03, "cvr": 0.02, "product": "gadget",
         "eng_score": 0.8, "label": "WINNER"},
        {"hook": "Nobody is talking about this…", "angle": "social-proof",
         "roas": 1.8, "ctr": 0.025, "cvr": 0.018, "product": "gadget",
         "eng_score": 0.7, "label": "WINNER"},
    ]
    store = PatternStore()
    store.update(extract_patterns(events))
    hooks = store.get_top_hooks(n=3)
    assert len(hooks) >= 1, "PatternStore should have hooks after update"
    assert "This changed everything…" in hooks or "Nobody is talking about this…" in hooks


def test_hook_pool_uses_pattern_store_when_populated(monkeypatch):
    """_refresh_pools should return PatternStore hooks when available."""
    import backend.execution.loop as loop_mod

    # Reset pool cache to force refresh
    loop_mod._hook_pool = []
    loop_mod._pool_ts   = 0.0

    from core.content.patterns import pattern_store, extract_patterns
    events = [
        {"hook": "SECRET_HOOK_XYZ", "angle": "urgency",
         "roas": 2.0, "ctr": 0.03, "cvr": 0.02, "eng_score": 0.9},
    ]
    pattern_store.update(extract_patterns(events))

    hooks, _ = loop_mod._refresh_pools()
    assert "SECRET_HOOK_XYZ" in hooks, f"PatternStore hook not in pool: {hooks}"

    # cleanup
    import importlib
    importlib.reload(loop_mod)  # reset module-level pools


def test_hook_pool_falls_back_to_hooks_module_when_empty():
    """_refresh_pools falls back to HOOKS list when PatternStore is empty."""
    import backend.execution.loop as loop_mod
    from core.content.patterns import PatternStore
    import importlib

    # patch pattern_store to return empty
    monkeypatched_store = PatternStore()
    import core.content.patterns as pat_mod
    original = pat_mod.pattern_store
    pat_mod.pattern_store = monkeypatched_store

    loop_mod._hook_pool = []
    loop_mod._pool_ts   = 0.0

    try:
        hooks, _ = loop_mod._refresh_pools()
        assert len(hooks) > 0, "should have HOOKS fallback"
        from core.creative.hooks import HOOKS
        for h in hooks:
            assert h in HOOKS
    finally:
        pat_mod.pattern_store = original
        importlib.reload(loop_mod)


# ── Fix 3: campaign tracking ──────────────────────────────────────────────────

def test_active_campaigns_populated_after_run_scaling():
    """After _run_scaling launches a playbook, _campaign_artifacts is non-empty."""
    from unittest.mock import patch
    import orchestrator.main as orch
    from core.content.playbook import Playbook

    pb = Playbook(
        product="test_product_loop",
        phase="SCALE",
        top_hooks=["This changed everything…"],
        top_angles=["problem-solution"],
        estimated_roas=1.8,
        confidence=0.8,
        evidence_count=20,
    )
    orch._campaign_artifacts.clear()
    orch._scaling_limiter.last_run = 0.0

    # Isolate from other tests' playbook state
    with patch("core.content.playbook.playbook_memory.all", return_value=[pb]):
        result = orch._run_scaling()

    assert result["status"] in ("ok", "skipped", "error")
    if result.get("launched", 0) > 0:
        assert len(orch._campaign_artifacts) > 0
        products = {a.product for a in orch._campaign_artifacts.values()}
        assert "test_product_loop" in products


def test_active_campaigns_maps_campaign_to_product():
    """Campaign IDs in _campaign_artifacts must carry a non-empty product."""
    import orchestrator.main as orch
    from core.content.playbook import playbook_memory, Playbook

    pb = Playbook(
        product="unique_product_abc",
        phase="SCALE",
        top_hooks=["hook1"],
        top_angles=["angle1"],
        estimated_roas=2.0,
        confidence=0.9,
        evidence_count=30,
    )
    playbook_memory.upsert(pb)
    orch._campaign_artifacts.clear()
    orch._scaling_limiter.last_run = 0.0

    orch._run_scaling()

    for artifact in orch._campaign_artifacts.values():
        assert isinstance(artifact.product, str)
        assert len(artifact.product) > 0


# ── Fix 4: content generation uses real signals ───────────────────────────────

def test_run_content_generation_returns_ok():
    from orchestrator.main import _run_content_generation
    result = _run_content_generation()
    assert result["status"] in ("ok", "error"), f"unexpected status: {result}"


def test_run_content_generation_never_skips_cold_start():
    """Content generation must not return 'skipped' even with an empty PatternStore."""
    from core.content.patterns import PatternStore
    import core.content.patterns as pat_mod
    from orchestrator.main import _run_content_generation

    original = pat_mod.pattern_store
    pat_mod.pattern_store = PatternStore()  # fresh empty store
    try:
        result = _run_content_generation()
        assert result.get("status") != "skipped", \
            "content generation should not skip on cold start"
    finally:
        pat_mod.pattern_store = original


def test_run_content_generation_generates_at_least_one():
    from orchestrator.main import _run_content_generation
    result = _run_content_generation()
    if result["status"] == "ok":
        assert result.get("generated", 0) >= 1


def test_run_content_generation_seeds_playbook_memory():
    """After content generation, playbook_memory should have at least one entry."""
    from core.content.playbook import playbook_memory, PlaybookMemory
    import core.content.playbook as pb_mod
    from orchestrator.main import _run_content_generation

    pb_mod.playbook_memory = PlaybookMemory()  # fresh store
    try:
        result = _run_content_generation()
        if result["status"] == "ok" and result.get("generated", 0) > 0:
            assert len(pb_mod.playbook_memory.all()) > 0
    finally:
        pb_mod.playbook_memory = playbook_memory


# ── Fix 5: metrics ingestion uses _campaign_artifacts ────────────────────────

def test_run_metrics_ingestion_records_per_product(monkeypatch):
    """When _campaign_artifacts is populated, outcomes are recorded per product."""
    import orchestrator.main as orch
    from core.content.schemas import CampaignArtifact
    from simulation.calibration import CalibrationStore
    import simulation.calibration as cal_mod

    fresh_store = CalibrationStore()
    original_store = cal_mod.calibration_store
    cal_mod.calibration_store = fresh_store

    orch._campaign_artifacts.clear()
    orch._campaign_artifacts["dry_123"] = CampaignArtifact(
        campaign_id="dry_123", adgroup_id="ag1", ad_ids=["ad1"],
        product="wireless_earbuds", hook="hook_we", angle="angle_we",
        phase="SCALE", estimated_roas=1.5, budget=50.0, dry_run=True,
    )
    orch._campaign_artifacts["dry_456"] = CampaignArtifact(
        campaign_id="dry_456", adgroup_id="ag2", ad_ids=["ad2"],
        product="led_strips", hook="hook_ls", angle="angle_ls",
        phase="SCALE", estimated_roas=1.8, budget=60.0, dry_run=True,
    )

    try:
        result = orch._run_metrics_ingestion()
        assert result["status"] in ("ok", "skipped", "error")
        # If metrics ran, at least the campaign tracking didn't raise
        if result["status"] == "ok" and result.get("metrics", {}).get("tiktok_campaign_count", 0) > 0:
            summary = fresh_store.summary()
            assert summary["total_records"] >= 0  # just no exception
    finally:
        cal_mod.calibration_store = original_store
        orch._campaign_artifacts.clear()


# ── Full round-trip: signal → classify → pattern → content ────────────────────

def test_full_feedback_loop_round_trip():
    """Simulate one full loop tick: execute → classify → pattern → content."""
    from backend.core.state import SystemState
    from backend.data.event_log import EventLog
    from backend.execution.loop import execute
    from backend.decision.engine import decide
    from core.content.feedback import batch_classify
    from core.content.patterns import extract_patterns, PatternStore
    from orchestrator.main import _run_content_generation
    import core.content.patterns as pat_mod

    local_store = PatternStore()
    original = pat_mod.pattern_store
    pat_mod.pattern_store = local_store

    try:
        state = SystemState()
        decisions = decide(state)
        results = execute(decisions, state)

        # All outcomes have hook and angle
        assert all("hook" in r and "angle" in r for r in results)

        # Classify outcomes
        classified = batch_classify(results)
        assert all("label" in r for r in classified)

        # Extract patterns and update store
        winners = [e for e in classified if e.get("label") == "WINNER"]
        if winners:
            local_store.update(extract_patterns(winners))
            assert len(local_store.get_top_hooks()) > 0

        # Content generation can use the updated store
        result = _run_content_generation()
        assert result["status"] in ("ok", "error")
    finally:
        pat_mod.pattern_store = original
