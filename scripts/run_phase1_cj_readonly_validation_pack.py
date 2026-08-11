"""Run one credential-safe, bounded CJ read-only validation pack.

This is intentionally an orchestration layer, not a second supplier adapter
or evaluation engine.  Its default path only evaluates local configuration.
An operator must provide both the server-side read-only gate and
``--allow-network`` before it delegates one bounded CJ candidate lookup to
the established Phase 1 validation harness.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sys
from dataclasses import replace
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.adapters.research.cj_readonly_api import explain_cj_read_only_readiness
from evaluation.commerce import compare_evaluations, evaluate_input, load_evaluation_input
from scripts import run_phase1_live_validation as live_validation

DEFAULT_OUTPUT_ROOT = ROOT / "artifacts" / "phase1_cj_readonly_validation"
SECRET_ENV_NAMES = (
    "CJ_EMAIL", "CJ_API_KEY", "CJ_ACCESS_TOKEN", "CJ_REFRESH_TOKEN",
    "SUPABASE_SERVICE_ROLE_KEY", "SENTRY_DSN",
)
SENSITIVE_KEY = re.compile(r"(?:authorization|api[_-]?key|access[_-]?token|refresh[_-]?token|secret|password|cookie)", re.I)
# Exact configured secret values are removed separately.  Only redact
# recognisable credential prefixes here: a generic long-string rule would
# incorrectly redact deterministic run IDs and replay hashes.
TOKENISH = re.compile(r"(?:bearer\s+[A-Za-z0-9._~+/-]+|(?:sk|rk|pk)_[A-Za-z0-9_-]{8,})", re.I)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Produce a sanitized, bounded CJ read-only supplier validation pack.")
    parser.add_argument("--provider", default="cj", choices=("cj",))
    parser.add_argument("--query", default="portable espresso maker")
    parser.add_argument("--allow-network", action="store_true", help="explicitly permit one bounded read-only supplier attempt")
    parser.add_argument("--competitor-urls", help="optional comma-separated public competitor URLs; omitted by default")
    parser.add_argument("--compare-against", help="optional existing validation artifact or directory")
    parser.add_argument("--workspace-id", default="phase1-cj-readonly-validation")
    parser.add_argument("--signal-fixture", default=str(ROOT / "tests/fixtures/commerce_mvp/public_signals.json"))
    parser.add_argument("--timestamp", help="deterministic output directory/report timestamp for tests or repeatable runs")
    parser.add_argument("--out-dir", help="defaults to artifacts/phase1_cj_readonly_validation/<timestamp>")
    parser.add_argument("--json", action="store_true", help="print the JSON validation-pack report (default)")
    parser.add_argument("--markdown", action="store_true", help="also write and print a Markdown validation-pack report")
    return parser


def _timestamp(value: str | None) -> str:
    return value or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _secret_values(environ: Mapping[str, str] | None = None) -> tuple[str, ...]:
    values = (environ or os.environ)
    return tuple(value for key in SECRET_ENV_NAMES if (value := values.get(key, "")))


def _safe_url(value: str) -> str:
    try:
        parts = urlsplit(value)
    except ValueError:
        return "[redacted-url]"
    if parts.scheme and parts.netloc:
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    return value


def sanitize_value(value: Any, *, secret_values: tuple[str, ...] = ()) -> Any:
    """Redact secret-shaped keys/values and strip URL query/fragment text.

    The normalized provider evidence itself is retained.  This function is
    deliberately stricter than the adapter because it protects a generated
    operator artifact even when an upstream dependency changes its output.
    """
    if isinstance(value, Mapping):
        return {
            str(key): "[redacted]" if SENSITIVE_KEY.search(str(key)) else sanitize_value(item, secret_values=secret_values)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_value(item, secret_values=secret_values) for item in value]
    if isinstance(value, tuple):
        return [sanitize_value(item, secret_values=secret_values) for item in value]
    if not isinstance(value, str):
        return value
    result = value
    for secret in secret_values:
        result = result.replace(secret, "[redacted]")
    if result.startswith(("http://", "https://")):
        return _safe_url(result)
    return TOKENISH.sub("[redacted]", result)


def _write_json(path: Path, value: Any, *, secret_values: tuple[str, ...]) -> None:
    safe = sanitize_value(value, secret_values=secret_values)
    content = json.dumps(safe, sort_keys=True, indent=2, ensure_ascii=False)
    _assert_artifact_safe(content, secret_values=secret_values)
    path.write_text(content + "\n", encoding="utf-8")


def _sanitize_json_file(path: Path, *, secret_values: tuple[str, ...]) -> None:
    if not path.is_file():
        return
    value = json.loads(path.read_text(encoding="utf-8"))
    _write_json(path, value, secret_values=secret_values)


def _sanitize_jsonl_file(path: Path, *, secret_values: tuple[str, ...]) -> None:
    if not path.is_file():
        return
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(sanitize_value(json.loads(line), secret_values=secret_values))
    content = "\n".join(json.dumps(row, sort_keys=True, ensure_ascii=False) for row in rows)
    if content:
        content += "\n"
    _assert_artifact_safe(content, secret_values=secret_values)
    path.write_text(content, encoding="utf-8")


def _assert_artifact_safe(content: str, *, secret_values: tuple[str, ...]) -> None:
    leaked = [secret for secret in secret_values if secret and secret in content]
    if leaked:
        raise ValueError("sanitized_artifact_contains_configured_secret")


def _preflight(readiness: Mapping[str, Any], *, provider: str, allow_network: bool) -> dict[str, Any]:
    status = str(readiness.get("status", "unknown"))
    return {
        "provider": provider,
        "status": status,
        "configured": bool(readiness.get("configured")),
        "credentials_present_redacted": bool(readiness.get("credentials_present_redacted")),
        "live_flag_enabled": bool(readiness.get("live_flag_enabled")),
        "allow_network": allow_network,
        "read_only": True,
        "mutated": False,
        "forbidden_actions": list(readiness.get("forbidden_actions", [])),
        "warnings": list(readiness.get("warnings", [])),
    }


def _supplier_summary(validation: Mapping[str, Any]) -> dict[str, Any]:
    supplier = validation.get("supplier_evidence", {}) if isinstance(validation, Mapping) else {}
    evidence = supplier.get("result") if isinstance(supplier, Mapping) else None
    statuses = evidence.get("field_status", {}) if isinstance(evidence, Mapping) else {}
    statuses = statuses if isinstance(statuses, Mapping) else {}
    observed = sorted(key for key, value in statuses.items() if value == "observed")
    missing = sorted(key for key, value in statuses.items() if value != "observed")
    total = len(statuses)
    return {
        "status": supplier.get("provider_status") or supplier.get("status") or "unavailable",
        "source": supplier.get("source") or "unavailable",
        "observed_fields": observed,
        "missing_fields": missing,
        "coverage": round(len(observed) / total, 4) if total else 0.0,
        "confidence": evidence.get("confidence") if isinstance(evidence, Mapping) else None,
        "price_observed": statuses.get("price") == "observed",
        "inventory_observed": statuses.get("inventory_quantity") == "observed",
        "shipping_observed": statuses.get("shipping_cost") == "observed",
        "sku_observed": statuses.get("sku") == "observed",
        "variant_observed": statuses.get("variants") == "observed",
        "warnings": list(supplier.get("warnings", [])) if isinstance(supplier, Mapping) else [],
    }


def _engine_metrics(report: Mapping[str, Any], engine: str) -> Mapping[str, Any]:
    engines = report.get("engines", {}) if isinstance(report, Mapping) else {}
    value = engines.get(engine, {}) if isinstance(engines, Mapping) else {}
    return value.get("metrics", {}) if isinstance(value, Mapping) else {}


def _comparison_summary(
    comparison: Mapping[str, Any] | None, *, baseline: Mapping[str, Any] | None = None,
    current: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(comparison, Mapping):
        return None
    deltas = comparison.get("deltas", {})
    deltas = deltas if isinstance(deltas, Mapping) else {}
    keys = {
        "supplier_observed_fields": "supplier_evidence.observed_field_count",
        "supplier_coverage": "supplier_evidence.field_observation_rate",
        "supplier_confidence": "supplier_evidence.confidence_mean",
        "supplier_price_observed": "supplier_evidence.supplier_observed_price_rate",
        "supplier_inventory_observed": "supplier_evidence.supplier_inventory_observed_rate",
        "supplier_shipping_observed": "supplier_evidence.supplier_shipping_observed_rate",
        "supplier_sku_observed": "supplier_evidence.supplier_sku_observed_rate",
        "supplier_variant_observed": "supplier_evidence.supplier_variant_observed_rate",
        "overall_confidence": "overall.overall_confidence",
        "evidence_completeness": "overall.evidence_completeness",
        "assumption_percentage": "overall.assumption_percentage",
        "margin_intelligence": "margin_intelligence.observed_margin_confidence",
    }
    summary = {name: deltas.get(metric) for name, metric in keys.items()} | {
        "ranking_stability": comparison.get("ranking_stability"),
        "improved_metrics": list(comparison.get("improved_metrics", [])),
        "worsened_metrics": list(comparison.get("worsened_metrics", [])),
    }
    baseline_quality = (baseline or {}).get("overall", {}).get("run_quality") if isinstance(baseline, Mapping) else None
    current_quality = (current or {}).get("overall", {}).get("run_quality") if isinstance(current, Mapping) else None
    summary["run_quality"] = {"baseline": baseline_quality, "current": current_quality, "changed": baseline_quality != current_quality}
    return summary


def _recommended_action(*, preflight_status: str, probe_status: str, supplier: Mapping[str, Any], evaluation: Mapping[str, Any] | None) -> str:
    if preflight_status == "credential_missing":
        return "set_credentials"
    if preflight_status == "live_flag_disabled":
        return "enable_readonly_flag"
    if preflight_status == "network_gate_required":
        return "rerun_with_allow_network"
    if preflight_status not in {"ready", "observed"}:
        return "check_cj_account_permissions"
    if probe_status in {"auth_failed", "endpoint_forbidden", "provider_failed"}:
        return "fix_auth"
    if probe_status in {"no_results", "product_not_found", "warehouse_unavailable"}:
        return "check_cj_account_permissions"
    if probe_status != "observed":
        return "harden_payload_mapping"
    if not supplier.get("price_observed"):
        return "harden_payload_mapping"
    quality = (evaluation or {}).get("overall", {}).get("run_quality") if isinstance(evaluation, Mapping) else None
    return "ready_for_phase1_live_results" if quality in {"medium", "high"} else "record_live_supplier_success"


def _markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Phase 1 CJ Read-Only Validation Pack", "",
        f"- Run: `{report['run_id']}`", f"- Mode: `{report['mode']}`", f"- Preflight: `{report['preflight_status']}`",
        f"- Live probe: `{report['live_probe_status']}`", f"- Supplier coverage: `{report['supplier_coverage']}`",
        f"- Supplier fields observed: `{len(report['supplier_observed_fields'])}`", f"- Recommended next action: `{report['recommended_next_action']}`", "",
        "## Safety", "",
    ]
    lines.extend(f"- {name}: `{value}`" for name, value in sorted(report["safety_assertions"].items()))
    lines += ["", "## Warnings", ""]
    lines.extend(f"- {warning}" for warning in report["warnings"]) or lines.append("- none")
    return "\n".join(lines) + "\n"


def run_validation_pack(args: argparse.Namespace) -> dict[str, Any]:
    timestamp = _timestamp(args.timestamp)
    out_dir = Path(args.out_dir) if args.out_dir else DEFAULT_OUTPUT_ROOT / timestamp
    out_dir.mkdir(parents=True, exist_ok=True)
    secrets = _secret_values()
    readiness = explain_cj_read_only_readiness(allow_network=args.allow_network)
    preflight = _preflight(readiness, provider=args.provider, allow_network=args.allow_network)
    _write_json(out_dir / "preflight_report.json", preflight, secret_values=secrets)

    validation: dict[str, Any] | None = None
    evaluation: dict[str, Any] | None = None
    comparison: dict[str, Any] | None = None
    live_attempt = False
    probe_status = preflight["status"]
    warnings = list(preflight["warnings"])
    if args.allow_network and preflight["status"] == "ready":
        # Call the existing harness once.  Its explicit candidate cap makes
        # this a single bounded supplier probe, not a preflight-plus-probe
        # double request.
        live_attempt = True
        invocation = [
            "--supplier-source", "authenticated_readonly", "--allow-authenticated-supplier", "--allow-network",
            "--max-authenticated-supplier-candidates", "1", "--query", args.query,
            "--workspace-id", args.workspace_id, "--signal-fixture", args.signal_fixture,
            "--out-dir", str(out_dir), "--timestamp", timestamp,
        ]
        if args.competitor_urls:
            invocation.extend(["--competitor-urls", args.competitor_urls])
        with contextlib.redirect_stdout(StringIO()):
            exit_code = live_validation.main(invocation)
        if exit_code != 0:
            warnings.append(f"validation_harness_exit:{exit_code}")
        _sanitize_json_file(out_dir / "validation_report.json", secret_values=secrets)
        _sanitize_jsonl_file(out_dir / "events.jsonl", secret_values=secrets)
        validation_path = out_dir / "validation_report.json"
        if validation_path.is_file():
            validation = json.loads(validation_path.read_text(encoding="utf-8"))
            current = evaluate_input(load_evaluation_input(out_dir, source="cj_validation_pack"))
            baseline_report: dict[str, Any] | None = None
            if args.compare_against:
                baseline = evaluate_input(load_evaluation_input(args.compare_against, source="comparison_baseline"))
                baseline_report = baseline.to_dict()
                current = replace(current, comparison=compare_evaluations(baseline, current))
            evaluation = current.to_dict()
            _write_json(out_dir / "evaluation_report.json", evaluation, secret_values=secrets)
            comparison = _comparison_summary(evaluation.get("comparison"), baseline=baseline_report, current=evaluation)
            probe_status = _supplier_summary(validation)["status"]
        else:
            probe_status = "provider_failed"
            warnings.append("validation_report_missing")
    elif not args.allow_network and preflight["status"] == "ready":
        probe_status = "network_gate_required"

    supplier = _supplier_summary(validation or {})
    supplier["status"] = probe_status if validation is None else supplier["status"]
    overall = evaluation.get("overall", {}) if evaluation else {}
    canonical_event_count = int(evaluation.get("event_count", 0)) if evaluation else 0
    report = {
        "run_id": f"cj-readonly-validation-{timestamp}", "timestamp": timestamp, "provider": args.provider,
        "mode": "live_readonly" if live_attempt else "preflight_only", "python_version": sys.version.split()[0],
        "network_gate": {"allow_network": bool(args.allow_network), "required": True, "network_used": live_attempt},
        "credentials_present_redacted": preflight["credentials_present_redacted"], "preflight_status": preflight["status"],
        "live_probe_attempted": live_attempt, "live_probe_status": supplier["status"], "supplier_source": supplier["source"],
        "supplier_observed_fields": supplier["observed_fields"], "supplier_missing_fields": supplier["missing_fields"],
        "supplier_coverage": supplier["coverage"], "supplier_confidence": supplier["confidence"],
        "supplier_price_observed": supplier["price_observed"], "supplier_inventory_observed": supplier["inventory_observed"],
        "supplier_shipping_observed": supplier["shipping_observed"], "supplier_sku_observed": supplier["sku_observed"],
        "supplier_variant_observed": supplier["variant_observed"],
        "commerce_run_status": (validation or {}).get("commerce_mvp_run", {}).get("status"),
        "evaluation_run_quality": overall.get("run_quality"), "overall_confidence": overall.get("overall_confidence"),
        "overall_evidence_completeness": overall.get("evidence_completeness"), "assumption_percentage": overall.get("assumption_percentage"),
        "canonical_event_count": canonical_event_count, "comparison": comparison,
        "warnings": sorted(set(warnings + supplier["warnings"] + list((evaluation or {}).get("warnings", [])))),
        "safety_assertions": {
            "read_only": True, "mutated": False, "no_credentials_in_artifacts": True,
            "no_raw_provider_payloads": True, "no_auth_headers": True, "single_bounded_supplier_probe": live_attempt,
        },
    }
    report["recommended_next_action"] = _recommended_action(
        preflight_status=report["preflight_status"], probe_status=report["live_probe_status"], supplier=supplier, evaluation=evaluation,
    )
    _write_json(out_dir / "validation_pack_report.json", report, secret_values=secrets)
    if args.markdown:
        markdown = _markdown(report)
        _assert_artifact_safe(markdown, secret_values=secrets)
        (out_dir / "validation_pack_report.md").write_text(markdown, encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.json and args.markdown:
        _parser().error("choose --json or --markdown")
    report = run_validation_pack(args)
    if args.markdown:
        print(_markdown(report), end="")
    else:
        print(json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
