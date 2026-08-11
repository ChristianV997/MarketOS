"""Deterministic Phase 1 readiness aggregation for the Commerce MVP.

This module deliberately consumes already-sanitized validation/evaluation
reports.  It never fetches a provider, runs a validation, writes an event, or
reads a secret value.  The result is an operator-facing control-plane view,
not a second scoring or orchestration system.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from backend.adapters.research.cj_readonly_api import explain_cj_read_only_readiness

REPORT_VERSION = "phase1-readiness-v1"
SAFE_ARTIFACT_ROOT = Path(__file__).resolve().parents[2] / "artifacts"
SENSITIVE_KEY = re.compile(r"(api[_-]?key|secret|token|password|authorization|cookie|email)", re.I)
TOKEN_VALUE = re.compile(r"(?:bearer\s+|sk_|gh[opsu]_|eyJ)[A-Za-z0-9._-]{12,}", re.I)

STATUS_VALUE = {
    "ready": 1.0,
    "live_observed": 1.0,
    "partially_ready": 0.65,
    "fixture_only": 0.4,
    "degraded": 0.3,
    "not_configured": 0.15,
    "unknown": 0.15,
    "blocked": 0.0,
}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _status(value: Any, *, observed: bool = False, structural: bool = False) -> str:
    text = str(value or "").lower()
    if observed:
        return "live_observed"
    if text in {"credential_missing", "live_flag_disabled", "network_gate_required", "not_configured"}:
        return "not_configured"
    if text in {"blocked", "auth_failed", "provider_failed", "provider_mismatch"}:
        return "blocked"
    if text in {"degraded", "malformed_payload", "network_error", "no_results"}:
        return "degraded"
    return "fixture_only" if structural else "unknown"


def _safe(value: Any) -> Any:
    """Redact accidental secrets in optional, operator-supplied artifacts."""
    if isinstance(value, Mapping):
        return {str(key): "[redacted]" if SENSITIVE_KEY.search(str(key)) else _safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_safe(item) for item in value]
    if isinstance(value, str) and TOKEN_VALUE.search(value):
        return "[redacted]"
    return value


def load_sanitized_artifact(path: str | Path | None) -> tuple[dict[str, Any], list[str], str | None]:
    """Load one JSON object safely; missing/malformed input is advisory."""
    if not path:
        return {}, [], None
    candidate = Path(path)
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, [f"artifact_unavailable:{candidate.name}"], str(candidate)
    if not isinstance(payload, Mapping):
        return {}, [f"artifact_root_must_be_object:{candidate.name}"], str(candidate)
    return dict(_safe(payload)), [], str(candidate)


@dataclass(frozen=True)
class Phase1ReadinessReport:
    report_version: str
    generated_at: str
    overall_status: str
    overall_score: float
    score_contributions: dict[str, dict[str, Any]]
    phase: str
    blocking_gates: tuple[str, ...]
    advisory_warnings: tuple[str, ...]
    evidence_summary: dict[str, Any]
    supplier_readiness: dict[str, Any]
    competition_readiness: dict[str, Any]
    opportunity_readiness: dict[str, Any]
    research_readiness: dict[str, Any]
    commerce_run_readiness: dict[str, Any]
    evaluation_readiness: dict[str, Any]
    event_readiness: dict[str, Any]
    credential_readiness: dict[str, Any]
    validation_pack_readiness: dict[str, Any]
    deployment_readiness: dict[str, Any]
    safety_readiness: dict[str, Any]
    next_best_action: str
    next_best_prompt_hint: str
    required_operator_inputs: tuple[str, ...]
    allowed_next_phases: tuple[str, ...]
    forbidden_next_phases: tuple[str, ...]
    source_artifacts: dict[str, str]
    provenance: dict[str, str]
    read_only: bool = True
    mutated: bool = False
    network_calls: bool = False

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        for key in ("blocking_gates", "advisory_warnings", "required_operator_inputs", "allowed_next_phases", "forbidden_next_phases"):
            result[key] = list(result[key])
        return result


def _engine(report: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    engines = report.get("engines", {})
    if isinstance(engines, Mapping):
        value = engines.get(name, {})
        return value if isinstance(value, Mapping) else {}
    return {}


def _metrics(report: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = _engine(report, name).get("metrics", {})
    return value if isinstance(value, Mapping) else {}


def _next_action(*, credential: Mapping[str, Any], pack: Mapping[str, Any], supplier: Mapping[str, Any], competition: Mapping[str, Any], safety: Mapping[str, Any]) -> tuple[str, str, tuple[str, ...]]:
    if safety["status"] == "blocked":
        return "resolve_safety_gate", "Resolve the encoded Phase 1 safety blocker before expanding capability.", ()
    credential_status = str(credential.get("provider_status", ""))
    if credential_status == "credential_missing":
        return "set_cj_credentials_and_run_validation_pack", "Set server-side CJ read-only credentials, then run the offline-first validation pack with explicit network approval.", ("CJ_EMAIL", "CJ_API_KEY")
    if credential_status in {"live_flag_disabled", "network_gate_required"}:
        return "enable_readonly_flag_and_run_validation_pack", "Enable only MARKETOS_SUPPLIER_AUTH_READONLY=1 and use the pack's explicit --allow-network gate.", ()
    if pack["status"] in {"unknown", "not_configured"}:
        return "run_credential_safe_cj_validation_pack", "Run the credential-safe CJ validation pack; its default mode is offline and reports the exact missing gate.", ()
    if supplier["status"] != "live_observed":
        return "run_live_cj_readonly_probe", "Run one bounded, authenticated CJ catalog probe after the preflight reports ready.", ()
    if competition["status"] != "live_observed":
        return "expand_js_competitor_benchmark", "Run the bounded JS competitor benchmark before widening supplier/provider scope.", ()
    return "deploy_readonly_validation_stack", "Deploy the read-only validation stack and keep all mutation phases gated behind an approval ledger.", ()


def score_contributions(categories: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Explain exactly how every readiness category contributes to /100."""
    weight = round(100 / len(categories), 4) if categories else 0.0
    return {
        name: {"status": item["status"], "weight": weight, "status_value": STATUS_VALUE[item["status"]], "points": round(weight * STATUS_VALUE[item["status"]], 2)}
        for name, item in sorted(categories.items())
    }


def build_phase1_readiness(
    *,
    validation_artifact: Mapping[str, Any] | None = None,
    evaluation_report: Mapping[str, Any] | None = None,
    comparison_report: Mapping[str, Any] | None = None,
    validation_pack_report: Mapping[str, Any] | None = None,
    benchmark_report: Mapping[str, Any] | None = None,
    public_market_benchmark_report: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
    generated_at: str = "deterministic",
    source_artifacts: Mapping[str, str] | None = None,
) -> Phase1ReadinessReport:
    """Create a deterministic report from structural capability and artifacts."""
    validation = dict(validation_artifact or {})
    evaluation = dict(evaluation_report or {})
    comparison = dict(comparison_report or {})
    pack = dict(validation_pack_report or {})
    benchmark = dict(benchmark_report or {})
    public_market = dict(public_market_benchmark_report or {})
    env = os.environ if environ is None else environ
    credential_raw = explain_cj_read_only_readiness(env)
    credential = {
        "status": _status(credential_raw.get("status"), structural=True),
        "provider": credential_raw.get("provider", "cj"),
        "provider_status": credential_raw.get("status"),
        "credentials_present": bool(credential_raw.get("credentials_present_redacted")),
        "live_flag_enabled": bool(credential_raw.get("live_flag_enabled")),
        "configured": bool(credential_raw.get("configured")),
        "read_only": True,
    }
    supplier_metrics = _metrics(evaluation, "supplier_evidence")
    pack_observed = list(pack.get("supplier_observed_fields", []))
    observed_fields = dict(supplier_metrics.get("observed_fields", {})) if isinstance(supplier_metrics.get("observed_fields"), Mapping) else {}
    supplier_observed = bool(pack_observed or supplier_metrics.get("authenticated_supplier_succeeded") or supplier_metrics.get("observed_field_count")) and str(pack.get("supplier_source", "")) == "authenticated_readonly"
    supplier = {
        "status": _status(pack.get("live_probe_status") or pack.get("preflight_status"), observed=supplier_observed, structural=True),
        "source": pack.get("supplier_source") or next(iter((supplier_metrics.get("supplier_source_distribution") or {}).keys()), "unavailable"),
        "observed_fields": sorted(set(pack_observed) | set(observed_fields)),
        "observed_field_count": int(pack.get("supplier_observed_fields_count", supplier_metrics.get("observed_field_count", len(pack_observed)) or 0)),
        "coverage": _number(pack.get("supplier_coverage", supplier_metrics.get("field_observation_rate"))),
        "confidence": _number(pack.get("supplier_confidence", supplier_metrics.get("confidence_mean"))),
        "price_observed": bool(pack.get("supplier_price_observed", supplier_metrics.get("supplier_observed_price_rate", 0) > 0)),
        "inventory_observed": bool(pack.get("supplier_inventory_observed", supplier_metrics.get("supplier_inventory_observed_rate", 0) > 0)),
        "shipping_observed": bool(pack.get("supplier_shipping_observed", supplier_metrics.get("supplier_shipping_observed_rate", 0) > 0)),
        "sku_observed": bool(pack.get("supplier_sku_observed", supplier_metrics.get("supplier_sku_observed_rate", 0) > 0)),
        "variant_observed": bool(pack.get("supplier_variant_observed", supplier_metrics.get("supplier_variant_observed_rate", 0) > 0)),
    }
    competition_metrics = _metrics(evaluation, "competition_intelligence")
    offers = int(competition_metrics.get("observed_competitor_count", validation.get("observed_competitor_offers", 0)) or 0)
    competition = {"status": "live_observed" if offers else _status(validation.get("status"), structural=True), "observed_offer_count": offers, "pricing_coverage": _number(competition_metrics.get("pricing_coverage")), "median_price": competition_metrics.get("pricing_median"), "duplicate_count": int(competition_metrics.get("duplicate_count", 0) or 0), "confidence": _number(validation.get("competition_confidence"))}
    opportunity_metrics = _metrics(evaluation, "opportunity_scoring")
    opportunity = {"status": "partially_ready" if opportunity_metrics.get("candidate_count") else "fixture_only", "candidate_count": int(opportunity_metrics.get("candidate_count", 0) or 0), "confidence": _number((opportunity_metrics.get("confidence_distribution") or {}).get("mean")), "high_confidence_count": int(opportunity_metrics.get("high_confidence_count", 0) or 0)}
    research_metrics = _metrics(evaluation, "research_portfolio")
    research = {"status": "partially_ready" if research_metrics.get("candidate_count") else "fixture_only", "candidate_count": int(research_metrics.get("candidate_count", 0) or 0), "cluster_count": int(research_metrics.get("cluster_count", 0) or 0), "cluster_quality": research_metrics.get("cluster_quality")}
    overall = evaluation.get("overall", {}) if isinstance(evaluation.get("overall"), Mapping) else {}
    commerce = {"status": "partially_ready" if evaluation else "fixture_only", "run_quality": overall.get("run_quality", "unknown"), "overall_confidence": _number(overall.get("overall_confidence")), "evidence_completeness": _number(overall.get("overall_evidence_completeness")), "assumption_percentage": overall.get("assumption_percentage")}
    reproducibility = evaluation.get("reproducibility", {}) if isinstance(evaluation.get("reproducibility"), Mapping) else {}
    eval_ready = {"status": "ready" if evaluation and reproducibility.get("reproducible") else "partially_ready" if evaluation else "fixture_only", "framework_present": True, "report_present": bool(evaluation), "comparison_present": bool(comparison), "run_quality": overall.get("run_quality"), "reproducible": bool(reproducibility.get("reproducible")), "warnings": list(reproducibility.get("warnings", []))}
    event_count = int(evaluation.get("event_count", validation.get("canonical_event_count", pack.get("canonical_event_count", 0))) or 0)
    event_ready = {"status": "ready" if event_count else "fixture_only", "canonical_event_count": event_count, "replay_available": bool(reproducibility.get("replay_hash_available")), "reproducible": bool(reproducibility.get("reproducible"))}
    pack_ready = {"status": "live_observed" if supplier_observed else _status(pack.get("live_probe_status") or pack.get("preflight_status"), structural=True) if pack else "unknown", "report_present": bool(pack), "preflight_status": pack.get("preflight_status", "not_run"), "live_probe_attempted": bool(pack.get("live_probe_attempted")), "live_probe_status": pack.get("live_probe_status", "not_run")}
    deployment = {"status": "partially_ready" if env.get("MARKETOS_EVENT_READ_JSONL_PATH") else "not_configured", "event_read_path_configured": bool(env.get("MARKETOS_EVENT_READ_JSONL_PATH")), "public_runs_enabled": str(env.get("MARKETOS_PUBLIC_COMMERCE_RUNS", "0")) == "1", "supabase_write_gate_enabled": str(env.get("MARKETOS_SUPABASE_CANONICAL_EVENTS", "0")) == "1", "operator_route": "/operator/events"}
    safety = {"status": "ready", "provider_writes_blocked": True, "read_only": True, "no_mutation_authority": True, "credentials_redacted": True, "artifact_inputs_sanitized": True}
    action, hint, required_inputs = _next_action(credential=credential, pack=pack_ready, supplier=supplier, competition=competition, safety=safety)
    public_top = str(public_market.get("top_candidate_from_public_market") or "")
    if credential_raw.get("status") == "credential_missing" and public_top:
        action = f"set_cj_credentials_and_validate_candidate:{public_top}"
        hint = "Configure CJ read-only credentials, then validate the highest-value public-market candidate with the credential-safe validation pack."
    categories = {"supplier": supplier, "competition": competition, "opportunity": opportunity, "research": research, "commerce": commerce, "evaluation": eval_ready, "events": event_ready, "credentials": credential, "validation_pack": pack_ready, "deployment": deployment, "safety": safety}
    contributions = score_contributions(categories)
    score = round(sum(item["points"] for item in contributions.values()), 1)
    blockers = []
    if credential_raw.get("status") == "credential_missing": blockers.append("cj_credentials_missing_for_live_supplier_proof")
    if supplier["status"] != "live_observed": blockers.append("authenticated_supplier_evidence_not_live_observed")
    if competition["status"] != "live_observed": blockers.append("competition_evidence_not_live_observed")
    warnings = []
    if not evaluation: warnings.append("evaluation_report_not_supplied")
    if not pack: warnings.append("validation_pack_report_not_supplied")
    if not deployment["event_read_path_configured"]: warnings.append("event_read_jsonl_path_not_configured")
    overall_status = "ready" if not blockers and score >= 75 else "blocked" if credential_raw.get("status") == "credential_missing" else "partially_ready"
    artifacts = dict(source_artifacts or {})
    evidence_summary = {"live_observed_supplier_fields": supplier["observed_field_count"], "live_observed_competitor_offers": competition["observed_offer_count"], "overall_evidence_completeness": commerce["evidence_completeness"], "overall_confidence": commerce["overall_confidence"], "assumption_percentage": commerce["assumption_percentage"], "benchmark_matrix_status": benchmark.get("status", "not_configured"), "best_candidate_id": benchmark.get("top_candidate_id"), "highest_validation_priority": benchmark.get("highest_validation_priority", {}), "public_market_benchmark_status": public_market.get("evidence_mode", "not_configured"), "candidates_tested": int(public_market.get("candidates_tested", 0) or 0), "competitor_pages_attempted": int(public_market.get("competitor_pages_attempted", 0) or 0), "competitor_offers_observed": int(public_market.get("competitor_offers_observed", 0) or 0), "pricing_coverage": _number(public_market.get("pricing_coverage")), "top_candidate_from_public_market": public_top or None, "remaining_supplier_blocker": public_market.get("remaining_supplier_blocker", "authenticated_supplier_evidence_not_live_observed")}
    return Phase1ReadinessReport(REPORT_VERSION, generated_at, overall_status, score, contributions, "phase1", tuple(sorted(set(blockers))), tuple(sorted(set(warnings))), evidence_summary, supplier, competition, opportunity, research, commerce, eval_ready, event_ready, credential, pack_ready, deployment, safety, action, hint, required_inputs, ("read_only_deployment", "bounded_competitor_benchmark"), ("supplier_mutation", "shopify_mutation", "ads_or_spend", "orders_payments_or_fulfillment", "broad_phase2_without_live_readiness"), artifacts, {"supplier": "authenticated_CJ_readonly_adapter_and_sanitized_reports", "competition": "evaluation_framework_and_sanitized_validation_reports", "safety": "static_phase1_policy"})


def build_from_paths(*, validation_artifact: str | Path | None = None, evaluation_report: str | Path | None = None, comparison_report: str | Path | None = None, validation_pack_report: str | Path | None = None, benchmark_report: str | Path | None = None, public_market_benchmark_report: str | Path | None = None, environ: Mapping[str, str] | None = None) -> Phase1ReadinessReport:
    sources: dict[str, str] = {}
    warnings: list[str] = []
    loaded: list[dict[str, Any]] = []
    for name, path in (("validation_artifact", validation_artifact), ("evaluation_report", evaluation_report), ("comparison_report", comparison_report), ("validation_pack_report", validation_pack_report), ("benchmark_report", benchmark_report), ("public_market_benchmark_report", public_market_benchmark_report)):
        value, issues, source = load_sanitized_artifact(path)
        loaded.append(value); warnings.extend(issues)
        if source: sources[name] = source
    report = build_phase1_readiness(validation_artifact=loaded[0], evaluation_report=loaded[1], comparison_report=loaded[2], validation_pack_report=loaded[3], benchmark_report=loaded[4], public_market_benchmark_report=loaded[5], environ=environ, source_artifacts=sources)
    if warnings:
        value = report.to_dict(); value["advisory_warnings"] = sorted(set(value["advisory_warnings"] + warnings))
        return Phase1ReadinessReport(**{key: tuple(item) if key in {"blocking_gates", "advisory_warnings", "required_operator_inputs", "allowed_next_phases", "forbidden_next_phases"} else item for key, item in value.items()})
    return report


__all__ = ["Phase1ReadinessReport", "build_from_paths", "build_phase1_readiness", "load_sanitized_artifact", "score_contributions"]
