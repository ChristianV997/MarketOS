"""Tests for container and deployment configuration hardening invariants."""
from pathlib import Path

import yaml

from backend.security.deployment_validation import validate_production_deployment

ROOT = Path(__file__).resolve().parents[2]


def test_dockerfile_hardening_invariants():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    lines = [line.strip() for line in dockerfile.splitlines() if line.strip() and not line.startswith("#")]

    # Python version matches .python-version
    python_version = (ROOT / ".python-version").read_text(encoding="utf-8").strip()
    assert f"FROM python:{python_version}-slim" in dockerfile

    # Non-root user created and switched to
    assert "USER marketos" in dockerfile
    assert "10001" in dockerfile
    assert "marketos" in dockerfile

    # Healthcheck defined targeting /health on port 3000
    assert "HEALTHCHECK" in dockerfile
    assert "3000/health" in dockerfile

    # Graceful shutdown stop signal
    assert "STOPSIGNAL SIGINT" in dockerfile

    # No reload flag in production container CMD
    cmd_line = [line for line in lines if line.startswith("CMD")][0]
    assert "--reload" not in cmd_line
    assert '3000' in cmd_line


def test_docker_compose_prod_hardening_invariants():
    compose_path = ROOT / "docker-compose.prod.yml"
    data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    services = data["services"]

    # Postgres service invariants
    db = services["db"]
    assert "ports" not in db or not db["ports"], "Production Postgres port must not be published to host"
    assert db.get("restart") == "unless-stopped"
    assert "healthcheck" in db

    # Postgres password must require environment variable rather than hardcoded insecure default
    raw_text = compose_path.read_text(encoding="utf-8")
    assert "5432:5432" not in raw_text
    assert "POSTGRES_PASSWORD: upos" not in raw_text
    assert "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD" in raw_text

    # Redis service invariants
    redis = services["redis"]
    assert redis.get("restart") == "unless-stopped"
    assert "healthcheck" in redis

    # API service invariants
    api = services["api"]
    assert api.get("restart") == "unless-stopped"
    assert api["environment"].get("MARKETOS_PUBLIC_COMMERCE_RUNS") == "0"


def test_render_and_railway_descriptors_stay_health_gated_and_secret_free():
    railway = (ROOT / "deploy/railway/railway.json").read_text(encoding="utf-8")
    render = (ROOT / "deploy/render/render.yaml").read_text(encoding="utf-8")
    assert "healthcheckPath" in railway
    assert "healthCheckPath: /health" in render
    assert "uvicorn backend.api:app" in railway
    assert "uvicorn backend.api:app" in render
    for content in (railway, render):
        assert "SERVICE_ROLE_KEY" not in content
        assert "sk-live" not in content
        assert "--reload" not in content


def test_docker_compose_grafana_invariants():
    raw_text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "GF_SECURITY_ADMIN_PASSWORD: admin" in raw_text


def test_deployment_validation_rejects_default_db_passwords_in_production():
    env = {
        "MARKETOS_ENVIRONMENT": "production",
        "MARKETOS_OPERATOR_TOKEN": "tok",
        "ALLOWED_ORIGINS": "https://app.marketos.com",
        "POSTGRES_PASSWORD": "upos",
    }
    report = validate_production_deployment(env)
    assert report["ready"] is False
    assert "insecure_default_database_password" in report["blockers"]

    env_url = {
        "MARKETOS_ENVIRONMENT": "production",
        "MARKETOS_OPERATOR_TOKEN": "tok",
        "ALLOWED_ORIGINS": "https://app.marketos.com",
        "DATABASE_URL": "postgresql://upos:upos@db:5432/upos",
    }
    report_url = validate_production_deployment(env_url)
    assert report_url["ready"] is False
    assert "insecure_default_database_password_in_url" in report_url["blockers"]
