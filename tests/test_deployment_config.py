"""Deployment configuration invariants that prevent duplicate cycle owners."""
from pathlib import Path


def test_compose_api_defers_cycle_ownership_to_orchestrator():
    compose = (Path(__file__).parents[1] / "docker-compose.yml").read_text(encoding="utf-8")
    assert "ORCHESTRATOR_HANDLES_CYCLES=true" in compose
    assert "python -m orchestrator.main" in compose


def test_env_example_keeps_standalone_api_cycle_owner_explicit():
    env_example = (Path(__file__).parents[1] / ".env.example").read_text(encoding="utf-8")
    assert "ORCHESTRATOR_HANDLES_CYCLES=false" in env_example


def test_ci_has_container_health_and_commerce_smoke_gate():
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "container-smoke:" in workflow
    assert "docker build --tag marketos:ci ." in workflow
    assert "/health" in workflow
    assert "/ready" in workflow
    assert "/commerce/cycle" in workflow
