"""Offline, credential-safe readiness for a hosted read-only Phase 1 API."""
from __future__ import annotations
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = (ROOT / "artifacts").resolve()
VERSION = "readonly-deployment-readiness-v1"
MUTATION_FLAGS = ("SHOPIFY_WRITE_ENABLED", "CJ_ORDER_ENABLED", "SUPPLIER_MUTATION_ENABLED", "PAYMENTS_ENABLED", "ADS_WRITE_ENABLED", "TIKTOK_ADS_WRITE_ENABLED", "FULFILLMENT_ENABLED", "CUSTOMER_MESSAGING_ENABLED")
WRITE_SECRETS = ("SHOPIFY_ADMIN_TOKEN", "STRIPE_SECRET_KEY", "META_ACCESS_TOKEN", "TIKTOK_ACCESS_TOKEN")

def enabled(value: Any) -> bool: return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}
def safe_artifact(value: str) -> bool:
    if not value: return False
    try: return ARTIFACTS in Path(value).resolve().parents
    except OSError: return False

@dataclass(frozen=True)
class ReadOnlyDeploymentReadinessReport:
    report_version: str; environment: str; platform: str; generated_at: str; overall_status: str
    blocking_gates: tuple[str, ...]; advisory_warnings: tuple[str, ...]; required_env: tuple[str, ...]; optional_env: tuple[str, ...]
    secret_presence_redacted: Mapping[str, bool]; unsafe_env_values: tuple[str, ...]; mutation_authority_status: str; network_authority_status: str
    supplier_readonly_status: str; validation_pack_status: str; readiness_endpoint_status: str; artifact_storage_status: str; jsonl_event_sink_status: str
    frontend_readiness_status: str; manual_workflow_status: str; recommended_next_action: str; operator_commands: tuple[str, ...]; safety_assertions: tuple[str, ...]
    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for name in ("blocking_gates", "advisory_warnings", "required_env", "optional_env", "unsafe_env_values", "operator_commands", "safety_assertions"): value[name] = list(value[name])
        value.update({"read_only": True, "mutated": False, "network_calls": False})
        return value

def build_readiness(*, environ: Mapping[str, str] | None = None, platform: str = "local", generated_at: str = "deterministic") -> ReadOnlyDeploymentReadinessReport:
    env = os.environ if environ is None else environ; platform = platform if platform in {"local", "railway", "render"} else "local"
    secrets = {name: bool(env.get(name)) for name in ("CJ_EMAIL", "CJ_API_KEY", *WRITE_SECRETS)}
    unsafe = [name for name in MUTATION_FLAGS if enabled(env.get(name))] + [name for name in WRITE_SECRETS if env.get(name) and not enabled(env.get("MARKETOS_MVP_MODE"))]
    supplier_ready = env.get("MARKETOS_SUPPLIER_PROVIDER") == "cj" and enabled(env.get("MARKETOS_SUPPLIER_AUTH_READONLY")) and secrets["CJ_EMAIL"] and secrets["CJ_API_KEY"]
    read_path, write_path = str(env.get("MARKETOS_EVENT_READ_JSONL_PATH", "")), str(env.get("MARKETOS_EVENT_WRITE_JSONL_PATH", ""))
    blockers = ["unsafe_mutation_authority_present"] if unsafe else []
    if not supplier_ready: blockers.append("cj_readonly_credentials_or_gate_missing")
    if not safe_artifact(read_path): blockers.append("event_read_path_not_under_artifacts")
    status = "blocked" if blockers else "ready"
    next_action = "remove_unsafe_mutation_authority" if unsafe else "configure_cj_readonly_secrets_and_run_preflight" if not supplier_ready else "run_manual_cj_readonly_validation_pack"
    return ReadOnlyDeploymentReadinessReport(VERSION, str(env.get("MARKETOS_ENVIRONMENT", platform)), platform, generated_at, status, tuple(blockers), tuple(["public_commerce_runs_remain_disabled"] if not enabled(env.get("MARKETOS_PUBLIC_COMMERCE_RUNS")) else []), ("MARKETOS_SUPPLIER_PROVIDER", "MARKETOS_SUPPLIER_AUTH_READONLY", "CJ_EMAIL", "CJ_API_KEY", "MARKETOS_EVENT_READ_JSONL_PATH"), ("MARKETOS_PHASE1_JS_RENDER", "CRAWL4AI_ALLOWED_DOMAINS", "SUPABASE_URL"), secrets, tuple(sorted(unsafe)), "unsafe_mutation_authority_present" if unsafe else "safe_readonly", "manual_network_gate_required", "ready" if supplier_ready else "credential_missing", "ready_to_run_manually" if supplier_ready else "credential_missing", "available", "configured" if safe_artifact(read_path) else "unsafe", "configured" if safe_artifact(write_path) else "not_configured", "configured" if env.get("VITE_API_BASE_URL") else "not_configured", "workflow_dispatch_only", next_action, ("python scripts/check_readonly_deployment_readiness.py --json", "python scripts/check_phase1_supplier_readonly_access.py --provider cj --json", "python scripts/run_phase1_cj_readonly_validation_pack.py --provider cj --query 'portable espresso maker' --allow-network --markdown"), ("no_credentials_in_output", "no_provider_mutations", "manual_network_approval_required", "read_only_only"))
