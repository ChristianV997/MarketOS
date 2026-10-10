from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from evaluation.commerce.readiness import build_from_paths, build_phase1_readiness, load_sanitized_artifact, score_contributions
from scripts.ai import impact_planner, run_local_quality_gate


def _evaluation(*, supplier_fields: int = 0, supplier_source: str = "unavailable", offers: int = 0, events: int = 0) -> dict:
    return {"event_count": events, "overall": {"run_quality": "low", "overall_confidence": 0.45, "overall_evidence_completeness": 0.25, "assumption_percentage": 0.8}, "reproducibility": {"reproducible": bool(events), "replay_hash_available": bool(events), "warnings": []}, "engines": {"supplier_evidence": {"metrics": {"observed_field_count": supplier_fields, "field_observation_rate": supplier_fields / 10, "confidence_mean": 0.6 if supplier_fields else 0.0, "observed_fields": {"price": 1} if supplier_fields else {}, "supplier_source_distribution": {supplier_source: 1}, "authenticated_supplier_succeeded": int(supplier_source == "authenticated_readonly_api"), "supplier_observed_price_rate": int(supplier_fields > 0), "supplier_inventory_observed_rate": 0, "supplier_shipping_observed_rate": 0, "supplier_sku_observed_rate": 0, "supplier_variant_observed_rate": 0}}, "competition_intelligence": {"metrics": {"observed_competitor_count": offers, "pricing_coverage": offers / 4 if offers else 0.0, "pricing_median": 99.0 if offers else None, "duplicate_count": 0}}, "opportunity_scoring": {"metrics": {"candidate_count": 2, "high_confidence_count": 1, "confidence_distribution": {"mean": 0.55}}}, "research_portfolio": {"metrics": {"candidate_count": 2, "cluster_count": 1, "cluster_quality": 0.5}}}}


def _pack(status: str = "observed") -> dict:
    return {"preflight_status": "ready", "live_probe_status": status, "live_probe_attempted": status != "not_run", "supplier_source": "authenticated_readonly", "supplier_observed_fields": ["title", "price"], "supplier_coverage": 0.2, "supplier_confidence": 0.2, "supplier_price_observed": True}


def test_no_artifact_is_deterministic_and_blocked_for_missing_credentials():
    first = build_phase1_readiness(environ={}).to_dict()
    assert first == build_phase1_readiness(environ={}).to_dict()
    assert first["overall_status"] == "blocked"
    # Offline public-market benchmark is preferred before credentialed supplier proof.
    assert first["next_best_action"] == "run_offline_public_market_benchmark"
    assert "public_market_benchmark_report_not_supplied" in first["advisory_warnings"]
    assert first["network_calls"] is False and first["mutated"] is False
    assert round(sum(item["points"] for item in first["score_contributions"].values()), 1) == first["overall_score"]


@pytest.mark.parametrize(
    "provider_status,expected",
    [
        ("credential_missing", "run_offline_public_market_benchmark"),
        ("live_flag_disabled", "enable_readonly_flag_and_run_validation_pack"),
        ("network_gate_required", "enable_readonly_flag_and_run_validation_pack"),
    ],
)
def test_next_action_for_supplier_config_gates(provider_status, expected):
    env = {"MARKETOS_SUPPLIER_PROVIDER": "cj"}
    if provider_status != "credential_missing":
        env.update({"CJ_EMAIL": "x", "CJ_API_KEY": "y", "MARKETOS_SUPPLIER_AUTH_READONLY": "1" if provider_status == "network_gate_required" else "0"})
    report = build_phase1_readiness(environ=env).to_dict()
    assert report["next_best_action"] == expected


@pytest.mark.parametrize("offers,expected", [(0, "fixture_only"), (1, "live_observed"), (3, "live_observed")])
def test_competition_readiness_tracks_observed_offers(offers, expected):
    report = build_phase1_readiness(evaluation_report=_evaluation(offers=offers), environ={"CJ_EMAIL": "x", "CJ_API_KEY": "y", "MARKETOS_SUPPLIER_AUTH_READONLY": "1"}).to_dict()
    assert report["competition_readiness"]["status"] == expected


def _public_market(*, offers: int = 3, mode: str = "fixture_demo", candidates: int = 2, top: str = "mini-thermal-printer") -> dict:
    return {
        "evidence_mode": mode,
        "network_used": mode == "public_live",
        "candidates_tested": candidates,
        "competitor_pages_attempted": offers,
        "competitor_offers_observed": offers,
        "pricing_coverage": 0.5 if offers else 0.0,
        "public_evidence_confidence": 0.55 if offers else 0.0,
        "top_candidate_from_public_market": top if offers else None,
        "remaining_supplier_blocker": "authenticated_supplier_evidence_not_live_observed",
        "next_best_action": f"set_cj_credentials_and_validate_candidate:{top}" if top else "set_cj_credentials_and_run_validation_pack",
    }


def test_fixture_public_market_advances_competition_without_live_claim():
    baseline = build_phase1_readiness(environ={}).to_dict()
    report = build_phase1_readiness(public_market_benchmark_report=_public_market(), environ={}).to_dict()
    assert report["competition_readiness"]["status"] == "partially_ready"
    assert report["competition_readiness"]["observed_offer_count"] == 3
    assert report["opportunity_readiness"]["status"] == "partially_ready"
    assert report["opportunity_readiness"]["candidate_count"] == 2
    assert report["evidence_summary"]["top_candidate_from_public_market"] == "mini-thermal-printer"
    assert report["next_best_action"] == "set_cj_credentials_and_validate_candidate:mini-thermal-printer"
    # Fixture/demo never clears the live-competition blocker or supplier proof gate.
    assert "competition_evidence_not_live_observed" in report["blocking_gates"]
    assert "authenticated_supplier_evidence_not_live_observed" in report["blocking_gates"]
    assert report["overall_score"] > baseline["overall_score"]
    assert report["network_calls"] is False and report["mutated"] is False


def test_public_live_market_marks_competition_live_observed_only():
    report = build_phase1_readiness(
        public_market_benchmark_report=_public_market(mode="public_live"),
        environ={"CJ_EMAIL": "x", "CJ_API_KEY": "y", "MARKETOS_SUPPLIER_AUTH_READONLY": "1"},
    ).to_dict()
    assert report["competition_readiness"]["status"] == "live_observed"
    assert report["competition_readiness"]["observed_offer_count"] == 3
    # Public GETs are not authenticated supplier proof.
    assert report["supplier_readiness"]["status"] != "live_observed"


def test_authenticated_supplier_evidence_is_live_observed():
    env = {"CJ_EMAIL": "x", "CJ_API_KEY": "y", "MARKETOS_SUPPLIER_AUTH_READONLY": "1"}
    report = build_phase1_readiness(evaluation_report=_evaluation(supplier_fields=2, supplier_source="authenticated_readonly_api", offers=1, events=12), validation_pack_report=_pack(), environ=env).to_dict()
    assert report["supplier_readiness"]["status"] == "live_observed"
    assert report["supplier_readiness"]["price_observed"] is True
    assert report["event_readiness"]["canonical_event_count"] == 12


@pytest.mark.parametrize("key", ["CJ_API_KEY", "authorization", "email", "nested_token"])
def test_artifact_secrets_are_redacted(tmp_path, key):
    path = tmp_path / "report.json"; path.write_text(json.dumps({key: "Bearer very-long-token-value-123456", "safe": 1}), encoding="utf-8")
    value, warnings, _ = load_sanitized_artifact(path)
    assert not warnings and value[key] == "[redacted]" and value["safe"] == 1


@pytest.mark.parametrize("content,warning", [("not-json", "artifact_unavailable"), ("[]", "artifact_root_must_be_object")])
def test_malformed_artifact_degrades_without_crash(tmp_path, content, warning):
    path = tmp_path / "bad.json"; path.write_text(content, encoding="utf-8")
    report = build_from_paths(evaluation_report=path, environ={}).to_dict()
    assert any(warning in item for item in report["advisory_warnings"])


def test_path_ingestion_records_sources_without_reading_network(tmp_path):
    path = tmp_path / "evaluation.json"; path.write_text(json.dumps(_evaluation(events=3)), encoding="utf-8")
    report = build_from_paths(evaluation_report=path, environ={}).to_dict()
    assert report["source_artifacts"]["evaluation_report"] == str(path)
    assert report["network_calls"] is False


def test_quality_gate_includes_readiness_summary():
    value = run_local_quality_gate.run(["evaluation/commerce/readiness.py"])
    assert value["phase1_readiness"]["next_best_action"]
    assert "evaluation" in value["recommended_ci_lanes"]


def test_impact_planner_uses_readiness_hint():
    result = impact_planner.plan(impact_planner.DEFAULT_BACKLOG, {"next_best_action": "run_cj_credentialed_readonly_validation"})
    assert result["ranked_backlog"][0]["task"] == "run_cj_credentialed_readonly_validation"


@pytest.mark.parametrize("status,value", [("ready", 1.0), ("live_observed", 1.0), ("partially_ready", 0.65), ("fixture_only", 0.4), ("degraded", 0.3), ("not_configured", 0.15), ("unknown", 0.15), ("blocked", 0.0)])
def test_score_contributions_explain_each_explicit_status(status, value):
    contribution = score_contributions({"example": {"status": status}})["example"]
    assert contribution["status_value"] == value
    assert contribution["weight"] == 100.0
    assert contribution["points"] == 100 * value


def test_cli_outputs_json_and_markdown(tmp_path):
    root = Path(__file__).resolve().parents[1]
    command = [sys.executable, "scripts/phase1_readiness_report.py", "--json"]
    result = subprocess.run(command, cwd=root, text=True, capture_output=True, check=True)
    assert json.loads(result.stdout)["read_only"] is True
    markdown = subprocess.run([sys.executable, "scripts/phase1_readiness_report.py", "--markdown"], cwd=root, text=True, capture_output=True, check=True)
    assert "# MarketOS Phase 1 Readiness" in markdown.stdout
    output = tmp_path / "out"; subprocess.run(command + ["--output", str(output)], cwd=root, text=True, capture_output=True, check=True)
    assert (output / "phase1_readiness_report.json").is_file()
