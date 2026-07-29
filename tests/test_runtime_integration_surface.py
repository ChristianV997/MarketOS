from __future__ import annotations

from types import SimpleNamespace


def test_generate_creative_routes_through_inference(monkeypatch):
    import backend.inference
    from core.creative.generator import generate_creative

    calls: dict[str, object] = {}

    def fake_complete(prompt: str, **kwargs):
        calls["prompt"] = prompt
        calls["kwargs"] = kwargs
        return SimpleNamespace(content="Hook. Problem. Solution. CTA.", provider="litellm")

    monkeypatch.setattr(backend.inference, "complete", fake_complete)
    result = generate_creative("widget", "social-proof")

    assert result == "Hook. Problem. Solution. CTA."
    assert "widget" in str(calls["prompt"])
    assert calls["kwargs"]["sequence_id"].startswith("creative-")


def test_generate_creative_falls_back_for_mock_provider(monkeypatch):
    import backend.inference
    from core.creative.generator import generate_creative

    monkeypatch.setattr(
        backend.inference,
        "complete",
        lambda *args, **kwargs: SimpleNamespace(content="generic", provider="mock"),
    )

    result = generate_creative("widget", "social-proof")
    assert result.startswith("[Script] Product: widget | Angle: social-proof")


def test_broker_getter_and_subscriptions_work():
    from backend.pubsub.broker import get_broker

    broker = get_broker()
    events: list[dict] = []
    sub_id = broker.subscribe(events.append)

    broker.publish("test.event", {"payload": 1}, source="test")
    broker.unsubscribe(sub_id)
    broker.publish("test.event", {"payload": 2}, source="test")

    assert len(events) == 1
    assert events[0]["type"] == "test.event"
    assert events[0]["source"] == "test"


def test_vector_telemetry_publishes_through_broker():
    from backend.pubsub.broker import get_broker
    from backend.vector.telemetry import emit_indexed

    broker = get_broker()
    events: list[dict] = []
    sub_id = broker.subscribe(events.append)
    emit_indexed("hooks", 2, source="vector-test")
    broker.unsubscribe(sub_id)

    assert any(
        event["type"] == "vector.indexed"
        and event["collection"] == "hooks"
        and event["count"] == 2
        for event in events
    )


def test_runtime_service_helpers_start_and_stop(monkeypatch):
    import backend.api as api

    calls: dict[str, object] = {"heartbeat": None, "started": False, "stopped": False}

    class FakeScheduler:
        def start(self):
            calls["started"] = True

        def stop(self):
            calls["stopped"] = True

    scheduler = FakeScheduler()

    monkeypatch.setattr(
        "backend.runtime.task_inventory.start_heartbeat_broadcaster",
        lambda interval_s=30.0: calls.__setitem__("heartbeat", interval_s),
    )
    monkeypatch.setattr(
        "backend.runtime.task_inventory.stop_heartbeat_broadcaster",
        lambda: calls.__setitem__("heartbeat", "stopped"),
    )
    monkeypatch.setattr(
        "backend.runtime.sleep.replay_scheduler.get_scheduler",
        lambda: scheduler,
    )

    api._start_runtime_services()
    api._stop_runtime_services()

    assert calls["started"] is True
    assert calls["stopped"] is True


def test_runtime_skill_registry_and_endpoints():
    # These endpoints live in api.routes.observability (extracted from
    # backend/api.py during the Tier-0-style route-split refactor, which
    # predates the branch-unification merge that brought this test in from
    # main) rather than as bare module-level functions on backend.api.
    from api.routes import observability as obs

    skills = obs.runtime_skills()
    assert any(skill["name"] == "safe_command" for skill in skills["skills"])

    executed = obs.runtime_skill_execute("safe_command", {"command": "pwd"})
    assert executed["trace"]["status"] == "ok"
    assert executed["result"]["success"] is True

    traces = obs.runtime_skill_traces()
    assert any(trace["skill"] == "safe_command" for trace in traces["traces"])


def test_runtime_sleep_status_and_provider_status_endpoints(monkeypatch):
    from api.routes import observability as obs

    class FakeRouter:
        def provider_status(self):
            return [{"name": "mock", "available": True}]

    class FakeFallbackPolicy:
        def with_guaranteed_mock(self):
            return ["mock"]

    monkeypatch.setattr(
        "backend.runtime.sleep.replay_scheduler.get_scheduler",
        lambda: SimpleNamespace(status=lambda: {"running": False, "cycle_count": 0}),
    )
    monkeypatch.setattr("backend.inference.get_router", lambda: FakeRouter())
    monkeypatch.setattr("backend.inference.policies.fallback_policy.FallbackPolicy", FakeFallbackPolicy)
    sleep_status = obs.runtime_sleep_status()
    provider_status = obs.runtime_inference_providers()

    assert "running" in sleep_status
    assert "providers" in provider_status
    assert "fallback_chain" in provider_status
