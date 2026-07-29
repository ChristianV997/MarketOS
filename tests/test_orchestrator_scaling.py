"""Regression tests for the Tier 0 runaway-campaign-launch fix:
_run_scaling used to be registered twice in Phase.SCALE's worker list with
no RateLimiter and no per-playbook relaunch cooldown, so a product whose
confidence crossed 0.6 could get a fresh campaign minted on every tick,
indefinitely. This locks in: (1) single registration, (2) a cooldown that
actually prevents an immediate relaunch of the same playbook."""


def test_run_scaling_registered_exactly_once_per_phase():
    from orchestrator.main import _PHASE_WORKERS, _run_scaling
    from core.system.phase_controller import Phase

    for phase in Phase:
        count = _PHASE_WORKERS.get(phase, []).count(_run_scaling)
        assert count <= 1, f"_run_scaling registered {count} times in {phase}"


def test_playbook_relaunch_cooldown_prevents_immediate_relaunch(monkeypatch):
    import orchestrator.main as main_mod
    import core.content.playbook as pb_mod
    from core.content.playbook import Playbook, PlaybookMemory

    fresh = PlaybookMemory()
    fresh.upsert(Playbook(
        product="cooldown-widget", phase="SCALE", top_hooks=[], top_angles=[],
        estimated_roas=2.0, confidence=0.9, evidence_count=100,
    ))
    monkeypatch.setattr(pb_mod, "playbook_memory", fresh)
    monkeypatch.setattr("backend.integrations.adobe_ajo.is_configured", lambda: False)

    launched_calls = []

    def fake_launch(pb_dict, phase):
        launched_calls.append(pb_dict["product"])
        return {"status": "ok", "campaign_id": f"camp_{len(launched_calls)}",
               "budget": 10.0, "dry_run": True, "adgroup_id": "ag_1", "ad_ids": []}

    monkeypatch.setattr("backend.integrations.tiktok_ads.launch_from_playbook", fake_launch)

    # Bypass the outer worker-level RateLimiter (Tier 0 also added one) so
    # this test isolates the per-playbook cooldown specifically.
    main_mod._scaling_limiter.last_run = 0.0
    result1 = main_mod._run_scaling()
    assert result1["status"] == "ok"
    assert result1["launched"] == 1
    assert launched_calls == ["cooldown-widget"]

    main_mod._scaling_limiter.last_run = 0.0
    result2 = main_mod._run_scaling()
    assert launched_calls == ["cooldown-widget"], (
        "same playbook launched again inside the cooldown window"
    )


def test_playbook_relaunch_allowed_after_cooldown_expires(monkeypatch):
    import orchestrator.main as main_mod
    import core.content.playbook as pb_mod
    from core.content.playbook import Playbook, PlaybookMemory

    fresh = PlaybookMemory()
    fresh.upsert(Playbook(
        product="stale-widget", phase="SCALE", top_hooks=[], top_angles=[],
        estimated_roas=2.0, confidence=0.9, evidence_count=100,
        last_launched_at=1.0,  # far enough in the past to be outside any cooldown
    ))
    monkeypatch.setattr(pb_mod, "playbook_memory", fresh)
    monkeypatch.setattr("backend.integrations.adobe_ajo.is_configured", lambda: False)

    launched_calls = []

    def fake_launch(pb_dict, phase):
        launched_calls.append(pb_dict["product"])
        return {"status": "ok", "campaign_id": f"camp_{len(launched_calls)}",
               "budget": 10.0, "dry_run": True, "adgroup_id": "ag_1", "ad_ids": []}

    monkeypatch.setattr("backend.integrations.tiktok_ads.launch_from_playbook", fake_launch)

    main_mod._scaling_limiter.last_run = 0.0
    result = main_mod._run_scaling()
    assert result["launched"] == 1
    assert launched_calls == ["stale-widget"]
