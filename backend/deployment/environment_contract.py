"""backend.deployment.environment_contract -- Checked-in environment contract model and validation.

Distinguishes:
- required vs optional variables
- forbidden in local dry-run (e.g. mutation flags, live provider credentials enabled)
- required only for staging (e.g. ALLOWED_ORIGINS, DATABASE_URL / POSTGRES_PASSWORD, REDIS_URL)
- live-provider credentials
- mutation flags
- database configuration
- CoderOS / agent configuration

Fails closed for missing required staging values and keeps local dry-run usable without credentials.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT_PATH = ROOT / "deploy" / "mvp" / "env.contract.json"

MUTATION_FLAG_KEYS = frozenset({
    "MARKETOS_PUBLIC_COMMERCE_RUNS",
    "MARKETOS_ENABLE_LIVE_ACTIONS",
    "SHOPIFY_WRITE_ENABLED",
    "CJ_ORDER_ENABLED",
    "SUPPLIER_MUTATION_ENABLED",
    "PAYMENTS_ENABLED",
    "ADS_WRITE_ENABLED",
    "TIKTOK_ADS_WRITE_ENABLED",
    "LOGISTICS_DISPATCH_ENABLED",
    "CUSTOMER_MESSAGING_ENABLED",
})

LIVE_PROVIDER_CREDENTIAL_KEYS = frozenset({
    "SHOPIFY_ACCESS_TOKEN",
    "SHOPIFY_ADMIN_TOKEN",
    "STRIPE_SECRET_KEY",
    "TIKTOK_ACCESS_TOKEN",
    "META_ACCESS_TOKEN",
    "CJ_API_KEY",
    "DATAFORSEO_API_KEY",
    "APIFY_API_TOKEN",
    "SERPAPI_API_KEY",
})

DATABASE_KEYS = frozenset({
    "DATABASE_URL",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "REDIS_URL",
})

CODEROS_AGENT_KEYS = frozenset({
    "CODEROS_ROOT",
    "CODEROS_EXECUTABLE",
    "MARKETOS_AGENT_MODE",
    "MARKETOS_AGENT_WORKTREE",
})

INSECURE_PASSWORDS = frozenset({
    "upos",
    "postgres",
    "admin",
    "password",
    "root",
    "123456",
})


def is_truthy(val: Any) -> bool:
    return str(val or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


@dataclass(frozen=True)
class VariableClassification:
    name: str
    category: str
    required_for: str
    sensitive_value: bool
    browser_allowed: bool
    default: str
    description: str


@dataclass(frozen=True)
class EnvironmentContract:
    version: int
    profile: str
    artifact_root: str
    variables: dict[str, VariableClassification]
    environments: dict[str, dict[str, Any]]
    forbidden_frontend_secrets: tuple[str, ...]
    live_provider_credentials: tuple[str, ...]
    mutation_flags: tuple[str, ...]
    database_configuration: tuple[str, ...]
    coderos_agent_configuration: tuple[str, ...]


@dataclass
class EnvironmentValidationReport:
    mode: str
    status: str
    ready: bool
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    classified_counts: dict[str, int] = field(default_factory=dict)
    no_credentials_required: bool = False
    fail_closed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "status": self.status,
            "ready": self.ready,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "classified_counts": dict(self.classified_counts),
            "no_credentials_required": self.no_credentials_required,
            "fail_closed": self.fail_closed,
        }


def load_environment_contract(path: Path | None = None) -> EnvironmentContract:
    contract_file = path or DEFAULT_CONTRACT_PATH
    if not contract_file.exists():
        raise FileNotFoundError(f"Environment contract file not found: {contract_file}")
    data = json.loads(contract_file.read_text(encoding="utf-8"))

    variables: dict[str, VariableClassification] = {}
    for var in data.get("variables", []):
        name = var["name"]
        cat = "core"
        if name in DATABASE_KEYS:
            cat = "database"
        elif name in LIVE_PROVIDER_CREDENTIAL_KEYS:
            cat = "live_provider_credential"
        elif name in MUTATION_FLAG_KEYS:
            cat = "mutation_flag"
        elif name in CODEROS_AGENT_KEYS:
            cat = "coderos_agent"

        variables[name] = VariableClassification(
            name=name,
            category=cat,
            required_for=var.get("required_for", "backend"),
            sensitive_value=bool(var.get("secret", False)),
            browser_allowed=bool(var.get("browser_allowed", False)),
            default=str(var.get("default", "")),
            description=str(var.get("description", "")),
        )

    default_environments = {
        "local_dry_run": {
            "description": "Local development and offline replay mode with zero required credentials",
            "credentials_required": False,
            "forbidden_enabled_variables": list(MUTATION_FLAG_KEYS),
        },
        "staging": {
            "description": "Controlled private staging deployment for end-to-end rehearsal",
            "required_variables": ["ALLOWED_ORIGINS", "DATABASE_URL", "POSTGRES_PASSWORD", "REDIS_URL"],
            "forbidden_enabled_variables": list(MUTATION_FLAG_KEYS),
            "fail_closed_on_missing_required": True,
        },
        "production": {
            "description": "Hardened production profile with operator authentication and private networking",
            "required_variables": ["ALLOWED_ORIGINS", "DATABASE_URL", "POSTGRES_PASSWORD", "REDIS_URL", "MARKETOS_OPERATOR_TOKEN"],
            "fail_closed_on_missing_required": True,
        },
    }

    raw_envs = data.get("environments") or default_environments

    return EnvironmentContract(
        version=data.get("version", 1),
        profile=data.get("profile", "marketos-mvp-island"),
        artifact_root=data.get("artifact_root", "artifacts"),
        variables=variables,
        environments=raw_envs,
        forbidden_frontend_secrets=tuple(data.get("forbidden_frontend_secret_names", [])),
        live_provider_credentials=tuple(data.get("live_provider_credentials", list(LIVE_PROVIDER_CREDENTIAL_KEYS))),
        mutation_flags=tuple(data.get("mutation_flags", list(MUTATION_FLAG_KEYS))),
        database_configuration=tuple(data.get("database_configuration", list(DATABASE_KEYS))),
        coderos_agent_configuration=tuple(data.get("coderos_agent_configuration", list(CODEROS_AGENT_KEYS))),
    )


def validate_environment(
    environ: Mapping[str, str] | None = None,
    mode: str = "local_dry_run",
    contract: EnvironmentContract | None = None,
) -> EnvironmentValidationReport:
    env = os.environ if environ is None else environ
    active_contract = contract or load_environment_contract()

    valid_modes = {"local_dry_run", "staging", "production"}
    if mode not in valid_modes:
        raise ValueError(f"Invalid mode '{mode}'. Must be one of {valid_modes}")

    blockers: list[str] = []
    warnings: list[str] = []

    # Count classifications
    counts = {
        "total_variables": len(active_contract.variables),
        "live_credentials_present": sum(1 for k in active_contract.live_provider_credentials if bool(env.get(k))),
        "mutation_flags_enabled": sum(1 for k in active_contract.mutation_flags if is_truthy(env.get(k))),
        "database_vars_configured": sum(1 for k in active_contract.database_configuration if bool(env.get(k))),
        "coderos_vars_configured": sum(1 for k in active_contract.coderos_agent_configuration if bool(env.get(k))),
    }

    # 1. Evaluate mutation flags
    for flag in active_contract.mutation_flags:
        val = env.get(flag)
        if is_truthy(val):
            if mode in {"local_dry_run", "staging"}:
                blockers.append(f"mutation_flag_{flag}_forbidden_in_{mode}")

    # 2. Mode-specific evaluation
    if mode == "local_dry_run":
        # In local dry-run: 0 credentials required, pure offline operation.
        # Check if live credentials exist: warn or block if active without gate
        for cred in active_contract.live_provider_credentials:
            if env.get(cred):
                warnings.append(f"live_credential_{cred}_present_in_local_dry_run_unused")

        ready = len(blockers) == 0
        return EnvironmentValidationReport(
            mode=mode,
            status="ready_local_dry_run" if ready else "blocked",
            ready=ready,
            blockers=blockers,
            warnings=warnings,
            classified_counts=counts,
            no_credentials_required=True,
            fail_closed=True,
        )

    elif mode == "staging":
        # Staging: requires explicit allowed origins, persistence config, safe passwords
        staging_cfg = active_contract.environments.get("staging", {})
        staging_required = staging_cfg.get("required_variables", [
            "ALLOWED_ORIGINS", "DATABASE_URL", "POSTGRES_PASSWORD", "REDIS_URL",
        ])

        for req in staging_required:
            val = env.get(req, "").strip()
            if not val:
                # If DATABASE_URL is present, POSTGRES_PASSWORD might be in it or optional, but check both
                if req == "DATABASE_URL" and env.get("POSTGRES_PASSWORD"):
                    continue
                if req == "POSTGRES_PASSWORD" and env.get("DATABASE_URL"):
                    continue
                blockers.append(f"missing_required_staging_variable_{req}")

        # Check for insecure database passwords
        pg_pass = env.get("POSTGRES_PASSWORD", "").strip().lower()
        if pg_pass in INSECURE_PASSWORDS:
            blockers.append("insecure_database_password")

        db_url = env.get("DATABASE_URL", "").strip().lower()
        if db_url and any(f":{p}@" in db_url for p in INSECURE_PASSWORDS):
            blockers.append("insecure_database_password_in_url")

        # In staging, public commerce runs must remain 0
        if is_truthy(env.get("MARKETOS_PUBLIC_COMMERCE_RUNS")):
            blockers.append("public_commerce_runs_forbidden_in_staging")

        ready = len(blockers) == 0
        return EnvironmentValidationReport(
            mode=mode,
            status="ready_staging" if ready else "blocked",
            ready=ready,
            blockers=blockers,
            warnings=warnings,
            classified_counts=counts,
            no_credentials_required=False,
            fail_closed=True,
        )

    else:  # production
        prod_cfg = active_contract.environments.get("production", {})
        prod_required = prod_cfg.get("required_variables", [
            "ALLOWED_ORIGINS", "DATABASE_URL", "POSTGRES_PASSWORD", "REDIS_URL", "MARKETOS_OPERATOR_TOKEN",
        ])

        for req in prod_required:
            if not env.get(req, "").strip():
                blockers.append(f"missing_required_production_variable_{req}")

        ready = len(blockers) == 0
        return EnvironmentValidationReport(
            mode=mode,
            status="ready_production" if ready else "blocked",
            ready=ready,
            blockers=blockers,
            warnings=warnings,
            classified_counts=counts,
            no_credentials_required=False,
            fail_closed=True,
        )


__all__ = [
    "EnvironmentContract",
    "EnvironmentValidationReport",
    "VariableClassification",
    "load_environment_contract",
    "validate_environment",
    "MUTATION_FLAG_KEYS",
    "LIVE_PROVIDER_CREDENTIAL_KEYS",
    "DATABASE_KEYS",
    "CODEROS_AGENT_KEYS",
]
