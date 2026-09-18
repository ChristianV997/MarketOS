import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_deployment_contract_is_machine_readable_and_classifies_secrets():
    contract = json.loads((ROOT / "deploy/mvp/env.contract.json").read_text(encoding="utf-8"))
    variables = {item["name"]: item for item in contract["variables"]}
    assert contract["profile"] == "marketos-mvp-island"
    assert variables["MARKETOS_EVENT_READ_JSONL_PATH"]["required_for"] == "backend"
    assert variables["MARKETOS_PUBLIC_COMMERCE_RUNS"]["default"] == "0"
    assert variables["SUPABASE_SERVICE_ROLE_KEY"]["secret"] is True
    assert variables["SUPABASE_SERVICE_ROLE_KEY"]["browser_allowed"] is False
    assert "SHOPIFY_ACCESS_TOKEN" in contract["forbidden_frontend_secret_names"]


def test_selected_platform_templates_are_present_and_secret_free():
    railway = (ROOT / "deploy/railway/railway.json").read_text(encoding="utf-8")
    render = (ROOT / "deploy/render/render.yaml").read_text(encoding="utf-8")
    vercel = (ROOT / "frontend/vercel.json").read_text(encoding="utf-8")
    assert "uvicorn backend.api:app" in railway
    assert "healthcheckPath" in railway
    assert "uvicorn backend.api:app" in render
    assert "MARKETOS_PUBLIC_COMMERCE_RUNS" in render
    assert '"outputDirectory": "dist"' in vercel
    for content in (railway, render, vercel):
        assert "SERVICE_ROLE_KEY" not in content
        assert "ACCESS_TOKEN" not in content


def test_environment_contract_loader_and_categories():
    from backend.deployment.environment_contract import (
        load_environment_contract,
    )
    contract = load_environment_contract()
    assert contract.profile == "marketos-mvp-island"
    assert "local_dry_run" in contract.environments
    assert "staging" in contract.environments
    assert "production" in contract.environments
    assert "SHOPIFY_ACCESS_TOKEN" in contract.live_provider_credentials
    assert "MARKETOS_PUBLIC_COMMERCE_RUNS" in contract.mutation_flags
    assert "DATABASE_URL" in contract.database_configuration
    assert "CODEROS_ROOT" in contract.coderos_agent_configuration


def test_local_dry_run_validation_usable_without_credentials():
    from backend.deployment.environment_contract import validate_environment
    report = validate_environment(environ={}, mode="local_dry_run")
    assert report.ready is True
    assert report.status == "ready_local_dry_run"
    assert report.no_credentials_required is True
    assert len(report.blockers) == 0


def test_local_dry_run_rejects_mutation_flags():
    from backend.deployment.environment_contract import validate_environment
    report = validate_environment(
        environ={"MARKETOS_PUBLIC_COMMERCE_RUNS": "1"},
        mode="local_dry_run",
    )
    assert report.ready is False
    assert report.status == "blocked"
    assert any("MARKETOS_PUBLIC_COMMERCE_RUNS" in b for b in report.blockers)


def test_staging_validation_fails_closed_on_missing_required_variables():
    from backend.deployment.environment_contract import validate_environment
    # Missing all staging variables
    report = validate_environment(environ={}, mode="staging")
    assert report.ready is False
    assert report.status == "blocked"
    assert any("missing_required_staging_variable" in b for b in report.blockers)


def test_staging_validation_rejects_insecure_database_passwords():
    from backend.deployment.environment_contract import validate_environment
    env = {
        "ALLOWED_ORIGINS": "https://staging.marketos.internal",
        "DATABASE_URL": "postgresql://marketos:upos@db:5432/marketos",
        "POSTGRES_PASSWORD": "upos",
        "REDIS_URL": "redis://redis:6379/0",
    }
    report = validate_environment(environ=env, mode="staging")
    assert report.ready is False
    assert report.status == "blocked"
    assert "insecure_database_password" in report.blockers


def test_staging_validation_succeeds_with_valid_configuration():
    from backend.deployment.environment_contract import validate_environment
    env = {
        "ALLOWED_ORIGINS": "https://staging.marketos.internal",
        "DATABASE_URL": "postgresql://marketos:StrongStagingPassw0rd!@db:5432/marketos",
        "POSTGRES_PASSWORD": "StrongStagingPassw0rd!",
        "REDIS_URL": "redis://redis:6379/0",
        "MARKETOS_PUBLIC_COMMERCE_RUNS": "0",
    }
    report = validate_environment(environ=env, mode="staging")
    assert report.ready is True
    assert report.status == "ready_staging"
    assert len(report.blockers) == 0
