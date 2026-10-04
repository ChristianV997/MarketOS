import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
_FROM_PYTHON = re.compile(
    r"^\s*FROM\s+(?:--platform=\S+\s+)?python:(\d+)\.(\d+)(?:\.\d+)?(?:[-\s@]|$)",
    re.IGNORECASE | re.MULTILINE,
)


def _major_minor(version: str) -> tuple[int, int]:
    major, minor, *_ = version.strip().split(".")
    return int(major), int(minor)


def _dockerfile_python_versions(text: str) -> list[tuple[int, int]]:
    return [(int(major), int(minor)) for major, minor in _FROM_PYTHON.findall(text)]


def test_dockerfile_matches_supported_python_and_runs_non_root():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    declared = _major_minor((ROOT / ".python-version").read_text(encoding="utf-8"))
    found = _dockerfile_python_versions(text)
    assert found, "Dockerfile declares no Python base image"
    assert set(found) == {declared}
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
