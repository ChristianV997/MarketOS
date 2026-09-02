from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from backend.mvp_commerce.opportunity import OpportunityCandidate
from backend.mvp_commerce.product_research import build_research_candidates
from evaluation.commerce.commerce_operations_cycle import (
    EVIDENCE_CLASSES,
    STAGE_ORDER,
    UNIFORM_STAGE_KEYS,
    build_commerce_operations_cycle,
    reject_unsafe_input,
)
from evaluation.commerce.opportunity_synthesis import build_product_opportunity_synthesis
from evaluation.trustos.gate_runner import evaluate_action as evaluate_trustos_action
from scripts.run_commerce_operations_cycle import main
from scripts.run_product_opportunity_synthesis import main as synthesis_main

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "commerce_operations"
SYNTHESIS_FIXTURES = ROOT / "tests" / "fixtures" / "opportunity_synthesis"
CLI = ROOT / "scripts" / "run_commerce_operations_cycle.py"
MODULE_PATHS = (
    ROOT / "evaluation" / "commerce" / "commerce_operations_cycle.py",
    ROOT / "scripts" / "run_commerce_operations_cycle.py",
)
FORBIDDEN_IMPORTS = {
    "httpx",
    "requests",
    "openai",
    "anthropic",
    "apify",
    "socket",
    "aiohttp",
    "urllib3",
    "boto3",
}


def load(name: str, folder: Path = FIXTURES) -> dict:
    return json.loads((folder / name).read_text(encoding="utf8"))


def pillars():
    return (
        load("marketplace_trend_report.json", SYNTHESIS_FIXTURES),
        load("supplier_feasibility_report.json", SYNTHESIS_FIXTURES),
        load("consumer_attention_report.json", SYNTHESIS_FIXTURES),
    )


def cycle(**kwargs):
    market, supplier, consumer = pillars()
    return build_commerce_operations_cycle(market, supplier, consumer, **kwargs)


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(CLI), *args], cwd=ROOT, text=True, capture_output=True, check=False)


def _opportunity_candidate(candidate_id: str = "c1") -> OpportunityCandidate:
    return OpportunityCandidate(
        candidate_id=candidate_id,
        workspace_id="test-workspace",
        query="widget",
        product_name="Widget",
        category_name="Home",
        evidence_signal_ids=(),
        evidence_titles=(),
        source_urls=(),
        source_count=0,
        source_local_score=0.0,
        recency_score=0.0,
        evidence_strength="weak",
        confidence_level="low",
        assumptions=(),
        unknowns=(),
        cannot_claim=(),
        recommended_next_action="gather_more_evidence",
    )


def test_evidence_classes_are_explicit():
    assert EVIDENCE_CLASSES == (
        "fixture_evidence",
        "plan_only",
        "dry_run",
        "blocked",
        "requires_approval",
        "unavailable",
        "client_safe_projection",
        "not_live_validated",
    )


def test_default_cycle_is_deterministic():
    first = cycle().to_dict()
    second = cycle().to_dict()
    assert first == second


def test_default_cycle_is_offline_and_not_live_validated():
    report = cycle().to_dict()
    assert report["report_version"] == "commerce-operations-cycle-v1"
    assert report["cycle_mode"] == "dry_run"
    assert report["overall_status"] == "plan_only"
    assert report["evidence_class"] == "not_live_validated"
    assert report["confidence_claim"] == "not_live_validated"
    assert report["live_validated"] is False
    assert report["read_only"] is True
    assert report["network_calls"] is False
    assert report["mutated"] is False
    assert report["artifacts_written"] is False
    assert report["synthesis"]["confidence_grade"] != "A_live_validated"
    assert report["synthesis"]["scoring_authority"].endswith("build_product_opportunity_synthesis")
    assert report["launch_draft_readiness"]["packs_written"] is False
    assert report["site_draft_readiness"]["publishing_authorized"] is False
    assert report["client_workspace"]["tenant_created"] is False
    blob = json.dumps(report)
    assert "A_live_validated" not in blob or report["synthesis"]["confidence_grade"] != "A_live_validated"


def test_synthesis_scores_are_delegated_not_invented():
    market, supplier, consumer = pillars()
    expected = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    report = build_commerce_operations_cycle(market, supplier, consumer).to_dict()
    assert report["synthesis"]["combined_opportunity_score"] == expected["combined_opportunity_score"]
    assert report["synthesis"]["confidence_grade"] == expected["confidence_grade"]
    assert report["synthesis"]["overall_recommendation"] == expected["overall_recommendation"]
    assert report["synthesis"]["top_candidate_id"] == expected["top_candidate_id"]


def test_empty_reports_do_not_fake_scores():
    report = build_commerce_operations_cycle(
        load("empty_marketplace_report.json"),
        load("empty_supplier_report.json"),
        load("empty_consumer_report.json"),
    ).to_dict()
    expected = build_product_opportunity_synthesis({}, {}, {}).to_dict()
    assert report["marketplace"]["status"] == "unavailable"
    assert "marketplace_candidates_missing" in report["blockers"]
    assert "supplier_candidates_missing" in report["blockers"]
    assert "consumer_candidates_missing" in report["blockers"]
    assert report["synthesis"]["combined_opportunity_score"] == expected["combined_opportunity_score"]
    assert report["synthesis"]["confidence_grade"] == expected["confidence_grade"]
    assert report["live_validated"] is False
    assert report["governor"].get("live_go") is not True


def test_missing_pillar_is_explicit_blocker_without_fake_scores():
    market, _, consumer = pillars()
    expected = build_product_opportunity_synthesis(market, None, consumer).to_dict()
    report = build_commerce_operations_cycle(market, None, consumer).to_dict()
    assert "supplier_pillar_missing" in report["blockers"]
    assert report["supplier"]["supplied"] is False
    assert report["synthesis"]["combined_opportunity_score"] == expected["combined_opportunity_score"]
    assert report["synthesis"]["overall_recommendation"] == expected["overall_recommendation"]
    assert report["synthesis"]["confidence_grade"] != "A_live_validated"
    assert report["governor"].get("live_go") is not True


def test_malformed_root_is_rejected():
    with pytest.raises(ValueError, match="malformed"):
        build_commerce_operations_cycle(["not", "an", "object"], None, None)


@pytest.mark.parametrize("name,needle", [
    ("secret_like_api_key.json", "api_key"),
    ("secret_like_token.json", "token"),
    ("raw_html_rejected.json", "html"),
    ("raw_payload_rejected.json", "raw_payload"),
])
def test_secret_like_and_raw_payloads_are_rejected_and_not_leaked(name, needle):
    payload = load(name)
    with pytest.raises(ValueError, match="secret-like or raw payload"):
        reject_unsafe_input(payload, label="fixture")
    with pytest.raises(ValueError, match="secret-like or raw payload"):
        build_commerce_operations_cycle(payload, None, None)
    try:
        build_commerce_operations_cycle(payload, None, None)
    except ValueError as exc:
        text = str(exc)
        assert "synthetic-secret-must-not-be-imported" not in text
        assert "Bearer synthetic-token-must-not-be-imported" not in text
        assert "reject-this-fixture" not in text
        assert "hidden-provider-body" not in text
        assert needle  # requested field remains a rejection trigger, not an echo requirement


def test_live_flag_fail_closes_as_blocked():
    report = cycle(live_requested=True).to_dict()
    assert report["overall_status"] == "blocked"
    assert report["cycle_mode"] == "blocked"
    assert report["evidence_class"] == "blocked"
    assert report["live_requested"] is True
    assert report["live_validated"] is False
    assert "live_mode_requested" in report["blockers"]
    assert report["governor"]["status"] == "blocked"
    assert report["governor"].get("live_go") is not True
    for decision in report["governor"].get("decisions") or []:
        assert decision.get("simulated_only") is True
        assert decision.get("trustos_decision") not in {None, "allow"}
        assert decision.get("outcome") != "allow"


def test_client_safe_projection_omits_secrets():
    report = cycle().to_dict()
    projection = report["client_safe_projection"]
    blob = json.dumps(projection).lower()
    for forbidden in ("api_key", "token", "password", "raw_payload", "raw_html", "<html", "sk-", "authorization"):
        assert forbidden not in blob
    assert projection["live_validated"] is False
    assert projection["launch_authorized"] is False
    assert projection["evidence_class"] == "client_safe_projection"


def test_new_modules_have_no_live_clients():
    for path in MODULE_PATHS:
        tree = ast.parse(path.read_text(encoding="utf8"), filename=str(path))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert imported.isdisjoint(FORBIDDEN_IMPORTS), path
        source = path.read_text(encoding="utf8")
        assert "requests.get" not in source
        assert "httpx" not in source
        assert "openai" not in source
        assert "anthropic" not in source
        assert "build_provider_registry" not in source


def test_build_research_candidates_unchanged_without_this_cycle():
    candidates = build_research_candidates([_opportunity_candidate("c1"), _opportunity_candidate("c2")])
    assert len(candidates) == 2
    for candidate in candidates:
        assert candidate.additional_evidence == {}
        assert candidate.to_dict()["additional_evidence_keys"] == []
        assert candidate.opportunity_score is None
        assert candidate.supplier_evidence is None
        assert candidate.competition_evidence is None


def test_existing_synthesis_cli_unchanged_without_this_cycle(capsys):
    synthesis_main(["--json"])
    report = json.loads(capsys.readouterr().out)
    assert report["report_version"] == "product-opportunity-synthesis-v1"
    assert "commerce-operations-cycle" not in json.dumps(report)
    assert report["network_calls"] is False


def test_cli_json_and_markdown_are_exclusive():
    result = run_cli("--json", "--markdown")
    assert result.returncode == 2


def test_cli_default_json_is_deterministic():
    first = run_cli("--json")
    second = run_cli("--json")
    assert first.returncode == 0
    assert second.returncode == 0
    assert json.loads(first.stdout) == json.loads(second.stdout)


def test_cli_markdown_mentions_readiness_and_safety():
    result = run_cli("--markdown")
    assert result.returncode == 0
    assert "Commerce Operations Readiness Cycle" in result.stdout
    assert "not live-validated" in result.stdout
    assert "No model, provider, or network calls" in result.stdout


def test_cli_does_not_write_artifacts_without_output(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["--json"]) == 0
    capsys.readouterr()
    assert list(tmp_path.iterdir()) == []


def test_cli_writes_only_when_output_is_set(tmp_path, capsys):
    assert main(["--output", str(tmp_path), "--json"]) == 0
    capsys.readouterr()
    names = {path.name for path in tmp_path.iterdir()}
    assert names == {
        "commerce_operations_cycle_report.json",
        "commerce_operations_cycle_report.md",
        "client_safe_projection.json",
    }
    projection = json.loads((tmp_path / "client_safe_projection.json").read_text(encoding="utf8"))
    assert "api_key" not in json.dumps(projection).lower()
    assert "launch_draft_pack.json" not in names
    assert "site_draft_pack.json" not in names


def test_cli_live_is_blocked(capsys):
    assert main(["--live", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["overall_status"] == "blocked"
    assert "live_mode_requested" in report["blockers"]
    assert report["live_validated"] is False


@pytest.mark.parametrize("name", [
    "malformed_cycle_input.json",
    "secret_like_api_key.json",
    "secret_like_token.json",
    "raw_html_rejected.json",
    "raw_payload_rejected.json",
])
def test_cli_rejects_malformed_and_secret_like_inputs(name):
    result = run_cli("--marketplace-trend-report", str(FIXTURES / name), "--json")
    assert result.returncode == 2
    combined = result.stdout + result.stderr
    assert "synthetic-secret-must-not-be-imported" not in combined
    assert "Bearer synthetic-token-must-not-be-imported" not in combined
    assert "reject-this-fixture" not in combined
    assert "hidden-provider-body" not in combined
    assert "<html" not in combined.lower()


def test_cli_path_traversal_is_rejected():
    result = run_cli("--consumer-attention-report", "..\\secret.json", "--json")
    assert result.returncode == 2
    assert "traversal" in result.stderr


def test_cli_missing_pillar_from_partial_inputs(capsys):
    path = SYNTHESIS_FIXTURES / "marketplace_trend_report.json"
    assert main(["--marketplace-trend-report", str(path), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert "supplier_pillar_missing" in report["blockers"]
    assert "consumer_pillar_missing" in report["blockers"]
    assert report["synthesis"]["confidence_grade"] != "A_live_validated"
    assert report["governor"].get("live_go") is not True


def _assert_uniform_stage(section: dict, *, blockers_alias: bool = False) -> None:
    for key in UNIFORM_STAGE_KEYS:
        assert key in section
    assert isinstance(section["evidence_references"], list)
    assert isinstance(section["blocking_reasons"], list)
    if blockers_alias:
        assert section["blocking_reasons"] == section.get("blockers")
    assert section["client_visible_projection_state"] in {
        "internal_only",
        "client_safe_projection",
        "blocked",
        "client_visible",
    }


def test_every_stage_uses_uniform_schema():
    report = cycle().to_dict()
    assert list(report["stages"]) == list(STAGE_ORDER)
    for name in STAGE_ORDER:
        _assert_uniform_stage(report[name], blockers_alias=True)
        _assert_uniform_stage(report["stages"][name])
        assert report["stages"][name]["status"] == report[name]["status"]
        assert report["stages"][name]["blocking_reasons"] == report[name]["blocking_reasons"]


def test_happy_plan_only_path_is_offline():
    report = cycle().to_dict()
    assert report["overall_status"] == "plan_only"
    assert report["cycle_mode"] == "dry_run"
    assert report["live_validated"] is False
    assert report["confidence_claim"] == "not_live_validated"
    assert report["synthesis"]["confidence_grade"] != "A_live_validated"
    assert report["product_validation"]["live_go"] is not True
    assert report["launch_draft_readiness"]["packs_written"] is False
    assert report["site_draft_readiness"]["publishing_authorized"] is False
    assert report["governor"].get("live_go") is not True
    assert report["approval_ledger"]["live_approval_granted"] is False


def test_product_validation_is_called_after_synthesis_before_launch():
    report = cycle().to_dict()
    validation = report["product_validation"]
    assert validation["presentation_builder"].endswith("product_validation_report.generate")
    assert "scoring_authority" not in validation
    assert report["synthesis"]["scoring_authority"].endswith("build_product_opportunity_synthesis")
    assert validation["source_reports"]["opportunity_synthesis"] == "supplied"
    assert validation["source_reports"]["launch_draft_pack"] == "missing"
    assert validation["source_reports"]["site_draft_pack"] == "missing"
    assert "executive_summary" not in validation
    assert "top_candidates" not in validation
    assert validation["overall_recommendation"] == report["synthesis"]["overall_recommendation"]
    assert list(STAGE_ORDER).index("product_validation") == list(STAGE_ORDER).index("synthesis") + 1
    assert list(STAGE_ORDER).index("launch_draft_readiness") > list(STAGE_ORDER).index("product_validation")


def test_governor_trustos_decision_is_passthrough_not_hardcoded():
    report = cycle().to_dict()
    public_beta = evaluate_trustos_action("public_beta_launch", generated_at="offline-deterministic").to_dict()
    publish_site = evaluate_trustos_action("publish_site", generated_at="offline-deterministic").to_dict()
    by_action = {item["action_type"]: item for item in report["governor"]["decisions"]}
    assert by_action["screen_product_opportunities"]["trustos_decision"] == public_beta["decision"]
    assert by_action["screen_product_opportunities"]["trustos_action"] == "public_beta_launch"
    assert by_action["generate_launch_draft"]["trustos_decision"] == publish_site["decision"]
    assert by_action["generate_site_draft"]["trustos_decision"] == publish_site["decision"]
    assert "allow" not in {
        by_action["screen_product_opportunities"]["trustos_decision"],
        by_action["generate_launch_draft"]["trustos_decision"],
    }


def test_insufficient_supplier_evidence_scenario():
    market, _, consumer = pillars()
    expected = build_product_opportunity_synthesis(market, load("insufficient_supplier_report.json"), consumer).to_dict()
    report = build_commerce_operations_cycle(
        market,
        load("insufficient_supplier_report.json"),
        consumer,
    ).to_dict()
    assert report["supplier"]["status"] == "unavailable"
    assert "supplier_candidates_missing" in report["blockers"]
    assert report["synthesis"]["overall_recommendation"] == expected["overall_recommendation"]
    assert expected["overall_recommendation"] in {"validate_supplier_first", "expand_supplier_research"}
    assert report["live_validated"] is False
    assert report["governor"].get("live_go") is not True
    assert report["confidence_claim"] != "A_live_validated"


def test_weak_consumer_attention_scenario():
    market, supplier, _ = pillars()
    consumer = load("weak_consumer_attention_report.json")
    expected = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    report = build_commerce_operations_cycle(market, supplier, consumer).to_dict()
    assert report["synthesis"]["overall_recommendation"] == expected["overall_recommendation"]
    assert expected["overall_recommendation"] in {"reject_low_attention", "expand_consumer_research", "reject_high_objection_risk"}
    assert report["product_validation"]["overall_recommendation"] == expected["overall_recommendation"]
    assert report["live_validated"] is False
    assert report["governor"].get("live_go") is not True


def test_poor_economics_scenario():
    market, _, consumer = pillars()
    supplier = load("poor_economics_supplier_report.json")
    expected = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    report = build_commerce_operations_cycle(market, supplier, consumer).to_dict()
    assert report["synthesis"]["overall_recommendation"] == expected["overall_recommendation"]
    assert expected["overall_recommendation"] in {"reject_poor_margin", "reject_logistics_risk", "reject_inventory_risk"}
    assert report["product_validation"]["overall_recommendation"] == expected["overall_recommendation"]
    assert report["live_validated"] is False
    assert report["governor"].get("live_go") is not True


def test_trustos_block_scenario():
    report = cycle().to_dict()
    decisions = {item.get("action"): item.get("decision") for item in report["trustos"].get("gates") or []}
    assert decisions.get("public_beta_launch") == "hard_block"
    assert decisions.get("launch_ad") == "hard_block"
    assert any(str(item).startswith("trustos_") and "hard_block" in str(item) for item in report["blockers"])
    assert report["trustos"]["required_approval_or_gate"] == "TrustOS evaluate_action"
    assert report["trustos"]["professional_conclusion"] is False
    assert report["governor"].get("live_go") is not True


def test_missing_approval_scenario():
    report = cycle().to_dict()
    sims = report["approval_ledger"].get("simulations") or []
    assert sims
    assert any(
        item.get("missing_conditions")
        or "denied" in str(item.get("result") or "")
        or "blocked" in str(item.get("result") or "")
        for item in sims
    )
    assert report["approval_ledger"]["live_approval_granted"] is False
    assert report["approval_ledger"]["status"] == "requires_approval"
    assert any("approval_missing:" in item or "approval_" in item for item in report["blockers"])
    assert report["governor"].get("live_go") is not True


def test_client_safe_export_block_scenario():
    report = cycle().to_dict()
    export = next((item for item in report["trustos"].get("gates") or [] if item.get("action") == "client_workspace_export"), None)
    assert export is not None
    assert export.get("decision") == "hard_block"
    assert report["client_workspace"]["tenant_created"] is False
    assert report["client_workspace"]["client_visible_projection_state"] in {"blocked", "client_safe_projection"}
    assert report["client_workspace"]["blocking_reasons"]
    assert report["client_safe_projection"]["launch_authorized"] is False
    assert report["governor"].get("live_go") is not True


def test_cycle_source_does_not_call_provider_registry():
    for path in MODULE_PATHS:
        source = path.read_text(encoding="utf8")
        assert "build_provider_registry" not in source
        assert "build_companyos_registry_report" not in source


def test_product_validation_does_not_run_phase1_path_builders(monkeypatch):
    import evaluation.commerce.product_validation_report as product_validation_report

    def _forbidden(*_args, **_kwargs):
        raise AssertionError("phase-1 path builder must not run from the commerce operations cycle")

    monkeypatch.setattr(product_validation_report, "build_benchmark_from_paths", _forbidden)
    monkeypatch.setattr(product_validation_report, "build_from_paths", _forbidden)
    monkeypatch.setattr(product_validation_report, "build_readiness", _forbidden)
    report = cycle().to_dict()
    validation = report["product_validation"]
    sources = validation["source_reports"]
    assert validation["status"] != "unavailable"
    assert sources["benchmark"] == "supplied"
    assert sources["readiness"] == "supplied"
    assert sources["benchmark"] != "structural_fixture"
    assert sources["readiness"] != "structural_fixture"
    assert "scoring_authority" not in validation
    assert report["synthesis"]["scoring_authority"].endswith("build_product_opportunity_synthesis")
    cycle_source = (ROOT / "evaluation" / "commerce" / "commerce_operations_cycle.py").read_text(encoding="utf8")
    assert "evaluation.commerce.readiness" not in cycle_source
    assert "backend.deployment.readiness" not in cycle_source
    assert "build_benchmark_from_paths" not in cycle_source
    assert "build_from_paths" not in cycle_source
