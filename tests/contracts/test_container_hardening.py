from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_dockerfile_matches_supported_python_and_runs_non_root():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    python_version = (ROOT / ".python-version").read_text(encoding="utf-8").strip()
    assert python_version.startswith("3.12")
    assert "FROM python:3.12-slim" in text
    assert "FROM python:3.14" not in text
    assert "USER marketos" in text
    assert "HEALTHCHECK" in text
    assert "--reload" not in text
    assert "STOPSIGNAL SIGINT" in text
    assert 'CMD ["uvicorn", "backend.api:app"' in text


def test_prod_compose_does_not_publish_postgres_or_hardcode_password():
    text = (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    assert "5432:5432" not in text
    assert "POSTGRES_PASSWORD: upos" not in text
    assert "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD" in text
    assert "healthcheck:" in text
    assert "--reload" not in text
    assert "MARKETOS_PUBLIC_COMMERCE_RUNS: \"0\"" in text


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
