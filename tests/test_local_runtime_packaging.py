"""Packaging invariants for credential-free local MarketOS startup."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
COMPOSE = ROOT / "docker-compose.yml"
LOCAL_ENV = ROOT / "deploy/local/.env.local.example"


def _compose() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8")) or {}


def test_local_env_example_exists_and_is_offline_safe():
    text = LOCAL_ENV.read_text(encoding="utf-8")
    assert "FF_PILLAR_A_INGESTION=false" in text
    assert "TIKTOK_DRY_RUN=true" in text
    assert "MARKETOS_PUBLIC_COMMERCE_RUNS=0" in text
    assert "ORCHESTRATOR_HANDLES_CYCLES=true" in text
    assert not re.search(r"(sk-[a-zA-Z0-9]{20,}|ghp_[a-zA-Z0-9]{20,}|AIza[a-zA-Z0-9]{30,})", text)


def test_compose_env_file_is_optional_with_offline_defaults():
    common = _compose()["x-common"]
    env_file = common["env_file"]
    assert isinstance(env_file, list)
    assert env_file[0]["path"] == ".env"
    assert env_file[0]["required"] is False
    environment = common["environment"]
    assert environment["FF_PILLAR_A_INGESTION"] == "false"
    assert environment["MARKETOS_PUBLIC_COMMERCE_RUNS"] == "0"
    assert environment["ORCHESTRATOR_HANDLES_CYCLES"] == "true"


def test_compose_api_has_liveness_healthcheck_and_cycle_guard():
    compose = COMPOSE.read_text(encoding="utf-8")
    api = _compose()["services"]["api"]
    assert "ORCHESTRATOR_HANDLES_CYCLES=true" in api["command"]
    healthcheck = api["healthcheck"]
    assert any("/health" in part for part in healthcheck["test"])
    assert api["depends_on"]["redis"]["condition"] == "service_healthy"


def test_dockerfiles_match_python_version_policy():
  dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
  worker = (ROOT / "Dockerfile.browser-use-worker").read_text(encoding="utf-8")
  python_version = (ROOT / ".python-version").read_text(encoding="utf-8").strip()
  assert f"python:{python_version}-slim" in dockerfile
  assert f"python:{python_version}-slim" in worker


def test_runbook_documents_health_and_readiness_split():
    runbook = (ROOT / "docs/LOCAL_RUNTIME_RUNBOOK.md").read_text(encoding="utf-8")
    assert "/health" in runbook
    assert "/ready" in runbook
    assert "uvicorn backend.api:app" in runbook
    assert "docker compose up api" in runbook
