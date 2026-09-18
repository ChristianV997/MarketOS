"""backend.deployment.promotion_fixtures -- Scenario fixtures for deployment promotion rehearsal.

Covers 15 canonical operational scenarios:
1. clean_local_dry_run
2. missing_python_dependency
3. missing_optional_node_dependency
4. docker_unavailable
5. invalid_staging_environment
6. weak_default_database_password
7. zero_step_ci
8. failed_health_check
9. port_collision
10. missing_ollama
11. coderos_unavailable
12. malformed_readiness_report
13. live_mutation_flag_accidentally_enabled
14. successful_offline_colab_matrix
15. deterministic_replay_across_runs
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from backend.deployment.promotion_rehearsal import (
    PromotionRehearsalBundle,
    execute_promotion_rehearsal,
)


def fixture_clean_local_dry_run() -> PromotionRehearsalBundle:
    """Clean local development dry-run with zero credentials and no mutations."""
    clean_env = {
        "MARKETOS_DEPLOYMENT_ENVIRONMENT": "local_dry_run",
        "MARKETOS_PUBLIC_COMMERCE_RUNS": "0",
        "MARKETOS_ENABLE_LIVE_ACTIONS": "0",
    }
    return execute_promotion_rehearsal(
        environment="local_dry_run",
        environ=clean_env,
    )


def fixture_missing_python_dependency() -> PromotionRehearsalBundle:
    """Required Python runtime dependency is missing."""
    clean_env = {"MARKETOS_DEPLOYMENT_ENVIRONMENT": "local_dry_run"}
    bundle = execute_promotion_rehearsal(
        environment="local_dry_run",
        environ=clean_env,
    )
    # Simulate detected missing python dependency
    bundle.blockers.append("diagnostic_missing_python_module: Required module 'nonexistent_package_xyz' missing.")
    bundle.remediations.append("[missing_python_module] Run `pip install -r requirements.txt`.")
    bundle.readiness_state = "failed"
    bundle.deterministic_hash = bundle.compute_hash()
    return bundle


def fixture_missing_optional_node_dependency() -> PromotionRehearsalBundle:
    """Optional Node/frontend dependency is absent."""
    clean_env = {"MARKETOS_DEPLOYMENT_ENVIRONMENT": "local_dry_run"}
    bundle = execute_promotion_rehearsal(
        environment="local_dry_run",
        environ=clean_env,
    )
    bundle.remediations.append("[missing_node_dependency] Run `cd frontend && npm ci`.")
    bundle.deterministic_hash = bundle.compute_hash()
    return bundle


def fixture_docker_unavailable() -> PromotionRehearsalBundle:
    """Docker daemon / CLI is not available in local environment."""
    clean_env = {"MARKETOS_DEPLOYMENT_ENVIRONMENT": "local_dry_run"}
    bundle = execute_promotion_rehearsal(
        environment="local_dry_run",
        environ=clean_env,
    )
    bundle.runtime["docker"] = "unavailable"
    bundle.deterministic_hash = bundle.compute_hash()
    return bundle


def fixture_invalid_staging_environment() -> PromotionRehearsalBundle:
    """Private staging configuration missing required DATABASE_URL / ALLOWED_ORIGINS."""
    empty_staging_env = {
        "MARKETOS_DEPLOYMENT_ENVIRONMENT": "staging",
    }
    return execute_promotion_rehearsal(
        environment="private_staging",
        environ=empty_staging_env,
    )


def fixture_weak_default_database_password() -> PromotionRehearsalBundle:
    """Staging database password uses an insecure default (e.g. 'postgres')."""
    insecure_env = {
        "ALLOWED_ORIGINS": "https://staging.internal.marketos",
        "DATABASE_URL": "postgresql://postgres:postgres@localhost:5432/marketos",
        "POSTGRES_PASSWORD": "postgres",
        "REDIS_URL": "redis://localhost:6379/0",
    }
    return execute_promotion_rehearsal(
        environment="private_staging",
        environ=insecure_env,
    )


def fixture_zero_step_ci() -> PromotionRehearsalBundle:
    """CI pipeline executed zero steps due to missing runners or billing lock."""
    clean_env = {"MARKETOS_DEPLOYMENT_ENVIRONMENT": "local_dry_run"}
    ci_override = {
        "ci_status": "ci_unavailable",
        "total_steps": 0,
        "runners_active": 0,
        "logs_available": False,
    }
    bundle = execute_promotion_rehearsal(
        environment="local_dry_run",
        environ=clean_env,
        ci_override=ci_override,
    )
    assert bundle.ci_evidence["state"] == "ci_unavailable"
    return bundle


def fixture_failed_health_check(tmp_path: Path) -> PromotionRehearsalBundle:
    """Container image missing HEALTHCHECK directive in Dockerfile."""
    bad_dockerfile = tmp_path / "Dockerfile.bad"
    bad_dockerfile.write_text(
        "FROM python:3.14-slim\nUSER marketos:marketos\nEXPOSE 3000\nCMD ['uvicorn']\n",
        encoding="utf-8",
    )
    clean_env = {"MARKETOS_DEPLOYMENT_ENVIRONMENT": "local_dry_run"}
    return execute_promotion_rehearsal(
        environment="local_dry_run",
        environ=clean_env,
        dockerfile_path=bad_dockerfile,
    )


def fixture_port_collision() -> PromotionRehearsalBundle:
    """Port 3000 collision detected by diagnostics."""
    clean_env = {"MARKETOS_DEPLOYMENT_ENVIRONMENT": "local_dry_run"}
    bundle = execute_promotion_rehearsal(
        environment="local_dry_run",
        environ=clean_env,
    )
    bundle.blockers.append("diagnostic_port_collision: Port 3000 is currently occupied.")
    bundle.remediations.append("[port_collision] Stop conflicting container or export PORT=3001.")
    bundle.readiness_state = "blocked"
    bundle.deterministic_hash = bundle.compute_hash()
    return bundle


def fixture_missing_ollama() -> PromotionRehearsalBundle:
    """Local Ollama instance unavailable; fallback to simulated model."""
    clean_env = {"MARKETOS_DEPLOYMENT_ENVIRONMENT": "local_dry_run"}
    bundle = execute_promotion_rehearsal(
        environment="local_dry_run",
        environ=clean_env,
    )
    bundle.remediations.append("[unavailable_ollama] Start ollama serve or use mock inference.")
    bundle.deterministic_hash = bundle.compute_hash()
    return bundle


def fixture_coderos_unavailable() -> PromotionRehearsalBundle:
    """CoderOS control plane unavailable; honestly reflected in status."""
    clean_env = {
        "MARKETOS_DEPLOYMENT_ENVIRONMENT": "local_dry_run",
        "CODEROS_ROOT": "",
    }
    bundle = execute_promotion_rehearsal(
        environment="local_dry_run",
        environ=clean_env,
    )
    bundle.coderos_status["status"] = "unavailable"
    bundle.deterministic_hash = bundle.compute_hash()
    return bundle


def fixture_malformed_readiness_report() -> Dict[str, Any]:
    """Malformed readiness report payload fails closed."""
    return {
        "status": "malformed",
        "missing_required_keys": ["environment", "readiness_state", "repository"],
        "fail_closed": True,
    }


def fixture_live_mutation_flag_accidentally_enabled() -> PromotionRehearsalBundle:
    """Live mutation flag was set in local_dry_run environment (must fail closed)."""
    mutation_env = {
        "MARKETOS_DEPLOYMENT_ENVIRONMENT": "local_dry_run",
        "MARKETOS_ENABLE_LIVE_ACTIONS": "1",
        "SHOPIFY_WRITE_ENABLED": "true",
    }
    return execute_promotion_rehearsal(
        environment="local_dry_run",
        environ=mutation_env,
    )


def fixture_successful_offline_colab_matrix() -> Dict[str, Any]:
    """Synthetic Colab benchmark matrix executed offline with 100% pass."""
    return {
        "execution_location": "local_workstation_executed",
        "colab_compute": {"available": False, "status": "unavailable"},
        "all_paths_passed": True,
        "total_paths": 9,
        "bit_identity_confirmed": True,
        "status": "passed",
    }


def fixture_deterministic_replay_across_runs() -> tuple[PromotionRehearsalBundle, PromotionRehearsalBundle]:
    """Two executions with identical inputs produce bit-identical hashes."""
    clean_env = {
        "MARKETOS_DEPLOYMENT_ENVIRONMENT": "local_dry_run",
        "MARKETOS_PUBLIC_COMMERCE_RUNS": "0",
    }
    run1 = execute_promotion_rehearsal("local_dry_run", environ=clean_env)
    run2 = execute_promotion_rehearsal("local_dry_run", environ=clean_env)
    return run1, run2


SCENARIO_FIXTURES = {
    "clean_local_dry_run": fixture_clean_local_dry_run,
    "missing_python_dependency": fixture_missing_python_dependency,
    "missing_optional_node_dependency": fixture_missing_optional_node_dependency,
    "docker_unavailable": fixture_docker_unavailable,
    "invalid_staging_environment": fixture_invalid_staging_environment,
    "weak_default_database_password": fixture_weak_default_database_password,
    "zero_step_ci": fixture_zero_step_ci,
    "port_collision": fixture_port_collision,
    "missing_ollama": fixture_missing_ollama,
    "coderos_unavailable": fixture_coderos_unavailable,
    "malformed_readiness_report": fixture_malformed_readiness_report,
    "live_mutation_flag_accidentally_enabled": fixture_live_mutation_flag_accidentally_enabled,
    "successful_offline_colab_matrix": fixture_successful_offline_colab_matrix,
    "deterministic_replay_across_runs": fixture_deterministic_replay_across_runs,
}
