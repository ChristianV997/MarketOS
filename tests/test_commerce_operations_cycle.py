from __future__ import annotations

import ast
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from backend.mvp_commerce.opportunity import OpportunityCandidate
from backend.mvp_commerce.product_research import build_research_candidates
from evaluation.commerce.commerce_operations_cycle import (
    EVIDENCE_CLASSES,
    PROOF_SEPARATION_BLOCKERS,
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
    "urllib",
    "urllib3",
    "subprocess",
    "boto3",
}
FORBIDDEN_IMPORT_NAMES = {
    "rank_opportunities",
    "score_opportunity",
    "build_from_paths",
    "build_benchmark_from_paths",
    "build_readiness",
    "build_provider_registry",
    "run_commerce_mvp_slice",
}
SECRET_EXPORT_KEYS = frozenset(
    {
        "api_key",
        "token",
        "html",
        "raw_payload",
        "raw_html",
        "password",
        "authorization",
    }
)
IDENTITY_AUTHORITY_KEYS = frozenset({"fingerprint", "source_family"})
CLIENT_SAFE_PROJECTION_KEYS = frozenset(
    {
        "report_version",
        "generated_at",
        "overall_status",
        "cycle_mode",
        "evidence_class",
        "confidence_claim",
        "live_validated",
        "top_candidate_id",
        "overall_recommendation",
        "confidence_grade",
        "blockers",
        "evidence_required",
        "approvals_required",
        "next_best_action",
        "launch_authorized",
        "publishing_authorized",
    }
)
EVIDENCE_MODE_LABELS = ("fixture", "manual_import", "simulated", "live_readonly")
REMAPPED_PROVENANCE = frozenset({"observed", "derived", "A_live_validated"})


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
    assert json.dumps(first, sort_keys=True, separators=(",", ":")) == json.dumps(
        second, sort_keys=True, separators=(",", ":")
    )


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
    ("nested_secret_report.json", "api_key"),
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
        imported_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
                imported_names.update(alias.name.split(".")[-1] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
                imported_names.update(alias.name for alias in node.names)
        assert imported.isdisjoint(FORBIDDEN_IMPORTS), path
        assert imported_names.isdisjoint(FORBIDDEN_IMPORT_NAMES), path
        source = path.read_text(encoding="utf8")
        assert "requests.get" not in source
        assert "httpx" not in source
        assert "openai" not in source
        assert "anthropic" not in source
        assert "urllib.request" not in source
        assert "urllib.parse" not in source
        assert "build_provider_registry" not in source
        assert "rank_opportunities" not in source
        assert "score_opportunity" not in source
        assert "opportunity_scoring_events" not in source
        assert "run_commerce_mvp_slice" not in source
        assert "build_from_paths" not in source
        assert "build_benchmark_from_paths" not in source
        assert "build_readiness" not in source


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
    assert first.stdout == second.stdout
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
    "nested_secret_report.json",
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


def _collect_keys(value) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            keys.add(str(key))
            keys.update(_collect_keys(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            keys.update(_collect_keys(item))
    return keys


def _assert_never_live_go(report: dict) -> None:
    assert report["overall_status"] in {"plan_only", "blocked", "unavailable"}
    assert report["live_validated"] is False
    assert report["confidence_claim"] == "not_live_validated"
    assert report["evidence_class"] not in {"A_live_validated", "live_validated"}
    assert report.get("governor", {}).get("live_go") is not True
    assert report.get("ranking", {}).get("live_go") is not True
    assert report.get("product_validation", {}).get("live_go") is not True
    assert report.get("approval_ledger", {}).get("live_approval_granted") is not True
    compact = json.dumps(report, separators=(",", ":"))
    assert '"live_go":true' not in compact


def _assert_no_identity_authority(report: dict) -> None:
    keys = _collect_keys(report)
    assert keys.isdisjoint(IDENTITY_AUTHORITY_KEYS)
    blob = json.dumps(report)
    assert "fingerprint" not in blob
    assert "source_family" not in blob


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
    assert list(STAGE_ORDER).index("ranking") == list(STAGE_ORDER).index("synthesis") + 1
    assert list(STAGE_ORDER).index("product_validation") == list(STAGE_ORDER).index("ranking") + 1
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
        assert "rank_opportunities" not in source
        assert "run_commerce_mvp_slice" not in source


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


def test_ranking_is_synthesis_order_not_rescored():
    market, supplier, consumer = pillars()
    expected = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    report = cycle().to_dict()
    ranking = report["ranking"]
    assert ranking["scoring_authority"].endswith("build_product_opportunity_synthesis")
    assert ranking["re_ranked"] is False
    assert ranking["duplicate_collapse"] == "last_wins"
    assert ranking["live_go"] is False
    assert ranking["confidence_claim"] == "not_live_validated"
    ids = [item["candidate_id"] for item in ranking["candidates"]]
    expected_ids = [item["candidate_id"] for item in expected["candidates"]]
    assert ids == expected_ids
    assert [item["combined_opportunity"] for item in ranking["candidates"]] == [
        item["combined_opportunity"] for item in expected["candidates"]
    ]
    assert ranking["top_candidate_id"] == expected["top_candidate_id"]
    for key in PROOF_SEPARATION_BLOCKERS:
        assert key in ranking["blocking_reasons"]
        assert ranking[key] is True
    for item in ranking["candidates"]:
        for pillar in item["pillars"].values():
            raw_mode = pillar["mode"]
            assert pillar["provenance"] == raw_mode
            assert raw_mode == "fixture"
            assert pillar["provenance"] != "observed"
            assert raw_mode != "observed"
        assert "A_live_validated" not in json.dumps(item)
        assert "fingerprint" not in item
        assert "source_family" not in json.dumps(item["pillars"])


def test_winner_loser_ranking_uses_synthesis_reject_reasons():
    report = cycle().to_dict()
    rows = report["ranking"]["candidates"]
    assert len(rows) >= 2
    assert rows[0]["rank"] == 1
    assert rows[0]["candidate_id"] == report["synthesis"]["top_candidate_id"]
    losers = [item for item in rows if item["reject_reason"]]
    assert losers
    assert all(str(item["reject_reason"]).startswith("reject") for item in losers)
    assert rows[0]["combined_opportunity"] >= rows[-1]["combined_opportunity"]


def test_strong_market_weak_supplier_next_action_is_supplier():
    report = build_commerce_operations_cycle(
        load("strong_market_report.json"),
        load("insufficient_supplier_report.json"),
        load("strong_market_consumer_report.json"),
    ).to_dict()
    expected = build_product_opportunity_synthesis(
        load("strong_market_report.json"),
        load("insufficient_supplier_report.json"),
        load("strong_market_consumer_report.json"),
    ).to_dict()
    assert report["synthesis"]["overall_recommendation"] == expected["overall_recommendation"]
    assert expected["overall_recommendation"] in {"validate_supplier_first", "expand_supplier_research"}
    action = f"{report['ranking']['next_action']} {report['next_best_action']} {expected['next_best_action']}"
    assert "supplier" in action.lower()
    assert "marketplace_is_not_supplier_proof" in report["blockers"]
    assert report["governor"].get("live_go") is not True


def test_strong_attention_weak_economics_uses_unit_economics_summary_only():
    market = load("strong_attention_market_report.json")
    supplier = load("weak_economics_supplier_report.json")
    consumer = load("strong_attention_consumer_report.json")
    expected = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    report = build_commerce_operations_cycle(market, supplier, consumer).to_dict()
    assert report["synthesis"]["overall_recommendation"] == expected["overall_recommendation"]
    assert expected["overall_recommendation"] == "reject_poor_margin"
    economics = report["synthesis"]["unit_economics_summary"]
    assert economics["gross_margin_percent"] == expected["unit_economics_summary"]["gross_margin_percent"]
    assert economics["gross_margin_percent"] == supplier["candidates"][0]["score"]["economics"]["gross_margin_percent"]
    decision = report["governor"]["decisions"][0]
    assert decision["unit_economics_source"] == "synthesis.unit_economics_summary"
    assert decision["unit_economics_score"] == max(0.0, min(1.0, float(economics["gross_margin_percent"])))
    assert "consumer_attention_is_not_ad_performance" in report["blockers"]
    assert report["governor"]["live_go"] is False


def test_strong_supplier_weak_demand_deprioritizes_without_fulfillment_proof():
    report = build_commerce_operations_cycle(
        load("weak_demand_market_report.json"),
        load("strong_supplier_report.json"),
        load("weak_demand_consumer_report.json"),
    ).to_dict()
    expected = build_product_opportunity_synthesis(
        load("weak_demand_market_report.json"),
        load("strong_supplier_report.json"),
        load("weak_demand_consumer_report.json"),
    ).to_dict()
    assert report["ranking"]["candidates"][0]["combined_recommendation"] == expected["overall_recommendation"]
    assert expected["overall_recommendation"] in {"reject_oversaturated", "expand_marketplace_research", "hold_for_manual_review"}
    assert "supplier_feasibility_is_not_fulfillment_proof" in report["blockers"]
    assert report["governor"].get("live_go") is not True


def test_conflicting_pillars_keep_named_blockers_without_silent_drop():
    report = build_commerce_operations_cycle(
        load("conflicting_market_report.json"),
        load("conflicting_supplier_report.json"),
        load("conflicting_consumer_report.json"),
    ).to_dict()
    expected = build_product_opportunity_synthesis(
        load("conflicting_market_report.json"),
        load("conflicting_supplier_report.json"),
        load("conflicting_consumer_report.json"),
    ).to_dict()
    assert report["ranking"]["candidate_count"] == expected["candidate_count"] == 1
    row = report["ranking"]["candidates"][0]
    assert row["blockers"]
    assert "low_margin_proxy" in row["blockers"] or "reject_poor_margin" in str(row["combined_recommendation"])
    assert report["synthesis"]["overall_recommendation"] == expected["overall_recommendation"]
    blob = json.dumps(report["ranking"])
    assert "conflict-widget" in blob
    assert report["live_validated"] is False


def test_nested_secret_in_object_array_is_rejected():
    payload = load("nested_secret_report.json")
    assert payload["imports"][0]["credentials"]["api_key"] == "synthetic-secret-must-not-be-imported"
    with pytest.raises(ValueError, match="secret-like or raw payload"):
        reject_unsafe_input(payload, label="fixture")
    with pytest.raises(ValueError, match="secret-like or raw payload"):
        build_commerce_operations_cycle(payload, None, None)
    try:
        build_commerce_operations_cycle(payload, None, None)
    except ValueError as exc:
        assert "synthetic-secret-must-not-be-imported" not in str(exc)


def test_similar_titles_with_different_ids_are_not_collapsed():
    market = load("similar_titles_market_report.json")
    supplier = load("similar_titles_supplier_report.json")
    consumer = load("similar_titles_consumer_report.json")
    expected = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    report = build_commerce_operations_cycle(market, supplier, consumer).to_dict()
    expected_ids = [item["candidate_id"] for item in expected["candidates"]]
    ids = [item["candidate_id"] for item in report["ranking"]["candidates"]]
    assert ids == expected_ids
    assert ids == ["lamp-alpha", "lamp-beta"]
    assert report["ranking"]["candidate_count"] == 2
    assert expected["candidate_count"] == 2
    titles = [item["title"] for item in report["ranking"]["candidates"]]
    assert titles == [item["title"] for item in expected["candidates"]]
    assert "desk lamp" in {item.casefold() for item in titles}
    assert "fingerprint" not in report["ranking"]["candidates"][0]


def test_ranking_pillar_labels_are_raw_pass_through():
    market = load("labeled_marketplace_report.json")
    supplier = load("labeled_supplier_report.json")
    consumer = load("labeled_attention_report.json")
    report = build_commerce_operations_cycle(market, supplier, consumer).to_dict()
    row = report["ranking"]["candidates"][0]
    marketplace = row["pillars"]["marketplace"]
    supplier_pillar = row["pillars"]["supplier"]
    consumer_pillar = row["pillars"]["consumer"]
    assert marketplace["source_type"] == "amazon_product_snapshot"
    assert marketplace["source_url"] == "https://example.test/listing/labeled-widget"
    assert marketplace["observed_at"] == "deterministic"
    assert marketplace["field_provenance"] == {"price": "observed", "review_count": "derived"}
    assert supplier_pillar["source_type"] == "cj_validation_pack_report"
    assert supplier_pillar["source_url"] == "https://example.test/supplier/CJ-LABELED-001"
    assert supplier_pillar["observed_at"] == "deterministic"
    assert supplier_pillar["field_provenance"] == {"unit_cost": "fixture", "shipping_cost": "observed"}
    assert supplier_pillar["supplier_product_id"] == "CJ-LABELED-001"
    assert supplier_pillar["sku"] == "SKU-LABELED-1"
    assert supplier_pillar["supplier_sku"] == "SKU-LABELED-1"
    assert consumer_pillar["source_type"] == "tiktok_creative_center_snapshot"
    assert consumer_pillar["source_url"] == "https://example.test/attention/labeled-widget"
    assert consumer_pillar["observed_at"] == "deterministic"
    assert consumer_pillar["field_provenance"] == {"hook": "manual_import"}
    assert "source_family" not in marketplace
    assert "source_family" not in supplier_pillar
    assert "source_family" not in consumer_pillar
    assert "fingerprint" not in row
    assert row["references"] == [
        "https://example.test/listing/labeled-widget",
        "https://example.test/supplier/CJ-LABELED-001",
        "CJ-LABELED-001",
        "https://example.test/attention/labeled-widget",
    ]
    markdown = build_commerce_operations_cycle(market, supplier, consumer).to_markdown()
    assert "amazon_product_snapshot" in markdown
    assert "CJ-LABELED-001" in markdown


def test_absent_observed_at_is_omitted_not_invented():
    market = load("absent_observed_at_marketplace_report.json")
    supplier = load("absent_observed_at_supplier_report.json")
    consumer = load("absent_observed_at_consumer_report.json")
    assert "observed_at" not in json.dumps(market)
    assert "observed_at" not in json.dumps(supplier)
    assert "observed_at" not in json.dumps(consumer)
    report = build_commerce_operations_cycle(market, supplier, consumer).to_dict()
    row = report["ranking"]["candidates"][0]
    for name, pillar in row["pillars"].items():
        assert "observed_at" not in pillar, name
        assert pillar.get("observed_at") != "deterministic"
        assert "source_type" not in pillar
        assert "source_url" not in pillar
        assert "field_provenance" not in pillar
        assert "supplier_product_id" not in pillar
        assert "sku" not in pillar
        assert "supplier_sku" not in pillar
    assert "observed_at" not in json.dumps(row["pillars"])


def test_duplicate_ids_collapse_last_wins_without_double_count():
    market = load("duplicate_ids_market_report.json")
    supplier = load("duplicate_ids_supplier_report.json")
    consumer = load("duplicate_ids_consumer_report.json")
    expected = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    report = build_commerce_operations_cycle(market, supplier, consumer).to_dict()
    ids = [item["candidate_id"] for item in report["ranking"]["candidates"]]
    assert ids == ["dup-widget"]
    assert report["ranking"]["candidate_count"] == 1
    assert expected["candidate_count"] == 1
    assert report["ranking"]["candidates"][0]["title"] == expected["candidates"][0]["title"]
    assert "first duplicate should lose" not in report["ranking"]["candidates"][0]["title"]


def test_stale_evidence_is_named_provenance_and_blocker():
    report = build_commerce_operations_cycle(
        load("stale_market_report.json"),
        load("stale_supplier_report.json"),
        load("stale_consumer_report.json"),
    ).to_dict()
    row = report["ranking"]["candidates"][0]
    assert row["pillars"]["marketplace"]["mode"] == "stale"
    assert row["pillars"]["marketplace"]["provenance"] == "stale"
    assert "stale_evidence:marketplace" in row["blockers"]
    assert "stale_evidence:marketplace" in report["blockers"]
    assert report["confidence_claim"] == "not_live_validated"
    assert report["governor"].get("live_go") is not True


def test_live_readonly_mode_stays_raw_never_observed():
    market = load("live_readonly_marketplace_report.json")
    supplier = load("live_readonly_supplier_report.json")
    consumer = load("live_readonly_attention_report.json")
    synthesis = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    assert synthesis["confidence_grade"] == "A_live_validated"
    report = build_commerce_operations_cycle(market, supplier, consumer).to_dict()
    assert report["confidence_claim"] == "not_live_validated"
    assert report["governor"]["live_go"] is False
    row = report["ranking"]["candidates"][0]
    for name, pillar in row["pillars"].items():
        assert pillar["mode"] == "live_readonly", name
        assert pillar["provenance"] == "live_readonly", name
        assert pillar["provenance"] != "observed"
        assert pillar["mode"] != "observed"
    assert report["marketplace"]["evidence_mode"] == "live_readonly"
    assert report["supplier"]["evidence_mode"] == "live_readonly"
    assert report["consumer_attention"]["evidence_mode"] == "live_readonly"


def test_governor_uses_synthesis_unit_economics_instead_of_zero_when_present():
    report = cycle().to_dict()
    expected = build_product_opportunity_synthesis(*pillars()).to_dict()
    margin = expected["unit_economics_summary"]["gross_margin_percent"]
    assert margin not in {None, 0, 0.0}
    for decision in report["governor"]["decisions"]:
        assert decision["unit_economics_source"] == "synthesis.unit_economics_summary"
        assert decision["unit_economics_score"] == max(0.0, min(1.0, float(margin)))
        assert decision["unit_economics_score"] != 0.0
        assert decision.get("workspace_decision") == "allow"
    assert report["governor"]["workspace_decision_authorizes_live"] is False
    assert report["governor"]["live_go"] is False


def test_trustos_and_governor_blockers_passthrough_keep_live_go_false():
    report = cycle().to_dict()
    assert report["governor"]["live_go"] is False
    assert report["trustos"]["professional_conclusion"] is False
    trustos_blockers = [item for item in report["blockers"] if str(item).startswith("trustos_")]
    governor_blockers = [item for item in report["blockers"] if str(item).startswith("governor_")]
    assert trustos_blockers
    assert governor_blockers
    for decision in report["governor"]["decisions"]:
        assert "TrustOS gate is blocked" in decision["blockers"] or decision["trustos_decision"] == "hard_block"
        assert decision.get("budget_checks") is not None


def test_governor_budget_limited_passthrough_keeps_live_go_false(monkeypatch):
    from dataclasses import replace

    import evaluation.commerce.commerce_operations_cycle as cycle_mod

    real = cycle_mod.evaluate_execution_request

    def limited(request, **kwargs):
        return real(replace(request, requested_amount=10_000.0, resource_type="ad_spend"), **kwargs)

    monkeypatch.setattr(cycle_mod, "evaluate_execution_request", limited)
    report = cycle().to_dict()
    assert report["governor"]["live_go"] is False
    reasons = " ".join(
        f"{item.get('reason')} {' '.join(str(check.get('reason') or '') for check in item.get('budget_checks') or [])} {' '.join(item.get('blockers') or [])}"
        for item in report["governor"]["decisions"]
    ).lower()
    assert "cap" in reasons or "budget" in reasons
    assert report["confidence_claim"] != "A_live_validated"


def test_provider_blocked_without_registry_clone():
    report = cycle().to_dict()
    assert report["approval_ledger"].get("registry_loaded") is False
    assert report["governor"]["live_go"] is False
    blob = json.dumps(report)
    assert "build_provider_registry" not in blob
    assert report["trustos"].get("provider_activation_decision")


def test_unverified_terms_and_policies_are_named_blocked_not_go():
    report = cycle().to_dict()
    blockers = [str(item) for item in report["blockers"]]
    trustos_blockers = [str(item) for item in report["trustos"].get("blocking_reasons") or []]
    site_blockers = [str(item) for item in report["site_draft_readiness"].get("blocking_reasons") or []]
    named = " ".join(blockers + trustos_blockers + site_blockers)
    assert "policies_present required" in named
    assert "lawyer_review required" in named
    assert "privacy_terms_approved" in named
    assert report["trustos"]["public_launch_decision"] == "blocked_for_public_beta"
    assert report["trustos"]["provider_activation_decision"] == "blocked_for_live_provider_activation"
    assert report["site_draft_readiness"]["publishing_authorized"] is False
    assert report["launch_draft_readiness"].get("launch_authorized") is not True
    _assert_never_live_go(report)


def test_terms_privacy_blockers_remain_named_on_dry_run_path():
    report = cycle().to_dict()
    assert report["cycle_mode"] == "dry_run"
    blob = json.dumps(report).lower()
    assert "privacy" in blob
    assert "terms" in blob
    assert any("policies_present" in str(item) for item in report["trustos"].get("blocking_reasons") or [])
    assert any("privacy_terms_approved" in str(item) for item in report["site_draft_readiness"].get("blocking_reasons") or [])
    assert report["governor"]["live_go"] is False
    assert report["overall_status"] != "go"
    _assert_never_live_go(report)


@pytest.mark.parametrize("mode", EVIDENCE_MODE_LABELS)
def test_evidence_mode_labels_pass_through_and_are_never_remapped(mode):
    pack = load("evidence_mode_pass_through.json")
    group = pack[mode]
    report = build_commerce_operations_cycle(group["marketplace"], group["supplier"], group["consumer"]).to_dict()
    assert report["marketplace"]["evidence_mode"] == mode
    assert report["supplier"]["evidence_mode"] == mode
    assert report["consumer_attention"]["evidence_mode"] == mode
    rows = report["ranking"]["candidates"]
    assert rows
    for row in rows:
        for name, pillar in row["pillars"].items():
            assert pillar["mode"] == mode, name
            assert pillar["provenance"] == mode, name
            assert pillar["mode"] not in REMAPPED_PROVENANCE
            assert pillar["provenance"] not in REMAPPED_PROVENANCE
            assert pillar["provenance"] != "observed"
            assert "fingerprint" not in pillar
            assert "source_family" not in pillar
    _assert_never_live_go(report)
    _assert_no_identity_authority(report)


def test_malformed_nested_non_object_fail_closes_without_fake_scores():
    _market, supplier, consumer = pillars()
    market = load("malformed_nested_non_object_marketplace.json")
    report = build_commerce_operations_cycle(market, supplier, consumer).to_dict()
    assert report["overall_status"] == "unavailable"
    assert report["synthesis"]["status"] == "unavailable"
    assert report["synthesis"].get("combined_opportunity_score") in {None, 0, 0.0}
    assert report["synthesis"].get("confidence_grade") not in {"A_live_validated", "C_fixture_or_partial"}
    assert "product_opportunity_synthesis_unavailable" in report["blockers"]
    assert report["ranking"]["status"] == "unavailable"
    assert report["ranking"].get("candidates") in (None, [], ())
    assert report["governor"].get("live_go") is not True
    _assert_never_live_go(report)
    _assert_uniform_stage(report["synthesis"], blockers_alias=True)
    _assert_uniform_stage(report["ranking"], blockers_alias=True)


def test_malformed_missing_id_record_is_not_scored():
    market = load("malformed_missing_id_marketplace.json")
    _, supplier, consumer = pillars()
    expected = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    report = build_commerce_operations_cycle(market, supplier, consumer).to_dict()
    ids = [item["candidate_id"] for item in report["ranking"]["candidates"]]
    assert ids == [item["candidate_id"] for item in expected["candidates"]]
    assert "ghost-row-must-not-be-scored" not in ids
    assert None not in ids
    assert "" not in ids
    assert report["ranking"]["candidate_count"] == expected["candidate_count"] == 2
    assert report["synthesis"]["combined_opportunity_score"] == expected["combined_opportunity_score"]
    _assert_never_live_go(report)


def test_happy_path_to_dict_and_projection_omit_secret_and_raw_keys():
    report = cycle().to_dict()
    projection = report["client_safe_projection"]
    keys = _collect_keys(report)
    assert keys.isdisjoint(SECRET_EXPORT_KEYS)
    assert _collect_keys(projection).isdisjoint(SECRET_EXPORT_KEYS)
    blob = json.dumps({"report": report, "projection": projection}).lower()
    for forbidden in ("api_key", "raw_payload", "raw_html", "<html", "sk-", "authorization"):
        assert forbidden not in blob
    assert '"token"' not in blob
    _assert_never_live_go(report)


def test_cli_packet_is_existing_to_dict_plus_client_safe_projection(tmp_path, capsys):
    assert main(["--output", str(tmp_path), "--json"]) == 0
    printed = json.loads(capsys.readouterr().out)
    names = {path.name for path in tmp_path.iterdir()}
    assert names == {
        "commerce_operations_cycle_report.json",
        "commerce_operations_cycle_report.md",
        "client_safe_projection.json",
    }
    packet = json.loads((tmp_path / "commerce_operations_cycle_report.json").read_text(encoding="utf8"))
    projection = json.loads((tmp_path / "client_safe_projection.json").read_text(encoding="utf8"))
    assert packet == printed
    assert projection == packet["client_safe_projection"]
    assert set(projection) == CLIENT_SAFE_PROJECTION_KEYS
    assert set(packet) == set(printed)
    _assert_no_identity_authority(packet)
    _assert_no_identity_authority(projection)
    assert packet["artifacts_written"] is True
    in_memory = cycle().to_dict()
    in_memory["artifacts_written"] = True
    in_memory["safety_summary"] = dict(in_memory["safety_summary"])
    in_memory["safety_summary"]["artifacts_written"] = True
    assert set(packet) == set(in_memory)
    assert "packet.json" not in names
    assert "fingerprint" not in names
    for path in tmp_path.iterdir():
        if path.suffix == ".json":
            blob = path.read_text(encoding="utf8")
            assert "fingerprint" not in blob
            assert "source_family" not in blob
            assert "api_key" not in blob.lower()
            assert "raw_payload" not in blob.lower()


def test_approval_ledger_unavailable_is_fail_closed_simulate_only(monkeypatch):
    import evaluation.commerce.commerce_operations_cycle as cycle_mod

    monkeypatch.setattr(cycle_mod, "simulate_action", None)
    monkeypatch.setattr(cycle_mod, "build_approval_ledger", None)
    report = cycle().to_dict()
    ledger = report["approval_ledger"]
    assert ledger["status"] == "unavailable"
    assert ledger["evidence_class"] == "unavailable"
    assert ledger.get("live_approval_granted") is not True
    assert ledger.get("live_go") is not True
    assert "approval_ledger_unavailable" in (ledger.get("blocking_reasons") or ledger.get("blockers") or [])
    _assert_uniform_stage(ledger, blockers_alias=True)
    _assert_never_live_go(report)


def test_approval_simulations_are_simulate_only_and_cannot_approve_now():
    report = cycle().to_dict()
    ledger = report["approval_ledger"]
    assert ledger["metadata_only"] is True
    assert ledger["registry_loaded"] is False
    assert ledger["live_approval_granted"] is False
    assert ledger["required_approval_or_gate"] == "Approval Ledger simulate_action"
    sims = ledger.get("simulations") or []
    assert {item["action"] for item in sims} == {"site_publish", "ad_launch", "supplier_order", "payment_creation"}
    for item in sims:
        assert item.get("can_be_approved_now") is False
        assert item.get("result") not in {"approved", "allow", "would_auto_allow"}
        assert item.get("status") in {"blocked", "requires_approval", "unavailable"}
        assert "live" not in str(item.get("result") or "")
    _assert_never_live_go(report)


def test_uniform_schema_holds_on_blocked_and_missing_pillar_paths():
    reports = (
        cycle(live_requested=True).to_dict(),
        build_commerce_operations_cycle(None, None, None).to_dict(),
    )
    for report in reports:
        assert list(report["stages"]) == list(STAGE_ORDER)
        for name in STAGE_ORDER:
            _assert_uniform_stage(report[name], blockers_alias=True)
            _assert_uniform_stage(report["stages"][name])
            assert report["stages"][name]["status"] == report[name]["status"]
        _assert_never_live_go(report)


def test_scoring_authority_stays_on_synthesis_generate_is_presentation_only():
    report = cycle().to_dict()
    owners = []
    for name in STAGE_ORDER:
        section = report[name]
        if "scoring_authority" in section:
            owners.append((name, section["scoring_authority"]))
    assert [name for name, _ in owners] == ["synthesis", "ranking"]
    assert all(auth.endswith("build_product_opportunity_synthesis") for _, auth in owners)
    validation = report["product_validation"]
    assert "scoring_authority" not in validation
    assert validation["presentation_builder"].endswith("product_validation_report.generate")
    assert report["ranking"]["re_ranked"] is False


def test_ranking_has_no_second_packet_or_identity_authority():
    report = cycle().to_dict()
    _assert_no_identity_authority(report)
    for row in report["ranking"]["candidates"]:
        assert "fingerprint" not in row
        assert "source_family" not in row
        assert "alias" not in row
        assert set(row["pillars"]) == {"marketplace", "supplier", "consumer"}
        for pillar in row["pillars"].values():
            assert "fingerprint" not in pillar
            assert "source_family" not in pillar
    assert set(report["client_safe_projection"]) == CLIENT_SAFE_PROJECTION_KEYS
    assert report["report_version"] == "commerce-operations-cycle-v1"


INVENTED_PROVENANCE = frozenset({"observed", "derived", "deterministic", "A_live_validated"})


def _strip_key(value, key: str):
    if isinstance(value, dict):
        return {item_key: _strip_key(item, key) for item_key, item in value.items() if item_key != key}
    if isinstance(value, list):
        return [_strip_key(item, key) for item in value]
    return value


def _dump(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _assert_not_authorized(report: dict) -> None:
    assert report.get("launch_draft_readiness", {}).get("launch_authorized") is not True
    assert report.get("site_draft_readiness", {}).get("publishing_authorized") is not True
    projection = report.get("client_safe_projection") or {}
    assert projection.get("launch_authorized") is not True
    assert projection.get("publishing_authorized") is not True
    assert projection.get("confidence_claim") == "not_live_validated"
    _assert_never_live_go(report)
    _assert_no_identity_authority(report)


def test_multi_stream_candidate_keeps_named_unmixed_streams():
    pack = load("multi_stream_candidate.json")
    market, supplier, consumer = pack["marketplace"], pack["supplier"], pack["consumer"]
    assert {item["marketplace"] for item in market["candidates"][0]["evidence"]} >= {"amazon", "shopify"}
    assert {item["supplier"] for item in supplier["candidates"][0]["offers"]} >= {"cj", "alibaba"}
    assert {item["platform"] for item in consumer["candidates"][0]["evidence"]} >= {"tiktok", "reddit"}
    expected = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    report = build_commerce_operations_cycle(market, supplier, consumer).to_dict()
    ranking = report["ranking"]
    assert ranking["re_ranked"] is False
    assert ranking["scoring_authority"].endswith("build_product_opportunity_synthesis")
    ids = [item["candidate_id"] for item in ranking["candidates"]]
    assert ids == [item["candidate_id"] for item in expected["candidates"]]
    assert ids == ["multi-stream-widget"]
    row = ranking["candidates"][0]
    assert set(row["pillars"]) == {"marketplace", "supplier", "consumer"}
    marketplace = row["pillars"]["marketplace"]
    supplier_pillar = row["pillars"]["supplier"]
    consumer_pillar = row["pillars"]["consumer"]
    market_blob = json.dumps(marketplace)
    supplier_blob = json.dumps(supplier_pillar)
    consumer_blob = json.dumps(consumer_pillar)
    assert "example.test/marketplace/" in market_blob
    assert "example.test/supplier/" not in market_blob
    assert "example.test/attention/" not in market_blob
    assert "example.test/supplier/" in supplier_blob
    assert "example.test/marketplace/" not in supplier_blob
    assert "example.test/attention/" not in supplier_blob
    assert "example.test/attention/" in consumer_blob
    assert "example.test/marketplace/" not in consumer_blob
    assert "example.test/supplier/" not in consumer_blob
    assert "CJ-MULTI-001" in supplier_blob or "ALI-MULTI-002" in supplier_blob
    assert "CJ-MULTI-001" not in market_blob
    assert "ALI-MULTI-002" not in market_blob
    for key in PROOF_SEPARATION_BLOCKERS:
        assert key in ranking["blocking_reasons"]
        assert ranking[key] is True
        assert key in report["blockers"]
    assert "fingerprint" not in row
    assert "source_family" not in json.dumps(row)
    _assert_not_authorized(report)


def test_unit_economics_assumptions_stay_labeled_not_observed_proof():
    market = load("strong_attention_market_report.json")
    supplier = load("weak_economics_supplier_report.json")
    consumer = load("strong_attention_consumer_report.json")
    fixture_assumptions = supplier["candidates"][0]["score"]["economics"]["assumptions"]
    assert fixture_assumptions
    expected = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    report = build_commerce_operations_cycle(market, supplier, consumer).to_dict()
    economics = report["synthesis"]["unit_economics_summary"]
    assert economics["assumptions"] == expected["unit_economics_summary"]["assumptions"]
    assert economics["assumptions"] == fixture_assumptions
    for item in economics["assumptions"]:
        assert isinstance(item, str) and item
        assert item not in INVENTED_PROVENANCE
        assert not item.startswith("observed")
        assert "A_live_validated" not in item
    assert any("assumption" in item for item in economics["assumptions"])
    assert economics["gross_margin_percent"] == expected["unit_economics_summary"]["gross_margin_percent"]
    decision = report["governor"]["decisions"][0]
    assert decision["unit_economics_source"] == "synthesis.unit_economics_summary"
    assert decision["unit_economics_score"] == max(0.0, min(1.0, float(economics["gross_margin_percent"])))
    assert report["governor"]["live_go"] is False
    assert report["synthesis"]["confidence_grade"] != "A_live_validated"
    _assert_not_authorized(report)


def test_missing_unit_economics_is_unavailable_not_zero_as_proof():
    market = load("strong_attention_market_report.json")
    supplier = copy.deepcopy(load("weak_economics_supplier_report.json"))
    consumer = load("strong_attention_consumer_report.json")
    supplier["candidates"][0]["score"].pop("economics", None)
    expected = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    report = build_commerce_operations_cycle(market, supplier, consumer).to_dict()
    compact = report["synthesis"].get("unit_economics_summary")
    assert compact in (None, {}, [])
    assert expected.get("unit_economics_summary") in (None, {}, [])
    governor = report["governor"]
    assert governor["unit_economics_source"] == "unavailable"
    assert "unit_economics_unavailable" in (governor.get("blocking_reasons") or governor.get("blockers") or [])
    assert governor["unit_economics_score"] == 0.0
    assert governor["live_go"] is False
    for decision in governor.get("decisions") or []:
        assert decision["unit_economics_source"] == "unavailable"
        assert decision["unit_economics_score"] == 0.0
        assert decision.get("unit_economics_score_is_observed_proof") is not True
    ranking_econ = (report["ranking"]["candidates"] or [{}])[0].get("unit_economics_summary")
    assert ranking_econ in (None, {}, [])
    _assert_not_authorized(report)


def test_mixed_stale_and_fresh_pillars_keep_named_provenance():
    market = load("stale_market_report.json")
    supplier = load("stale_supplier_report.json")
    consumer = load("stale_consumer_report.json")
    assert market["evidence_mode"] == "stale"
    assert supplier["candidates"][0]["offers"][0]["evidence_mode"] == "fixture"
    assert consumer["candidates"][0]["evidence"][0]["evidence_mode"] == "fixture"
    report = build_commerce_operations_cycle(market, supplier, consumer).to_dict()
    assert report["ranking"]["candidate_count"] >= 1
    row = report["ranking"]["candidates"][0]
    assert row["candidate_id"] == "stale-widget"
    marketplace = row["pillars"]["marketplace"]
    supplier_pillar = row["pillars"]["supplier"]
    consumer_pillar = row["pillars"]["consumer"]
    assert marketplace["mode"] == marketplace["provenance"] == "stale"
    assert supplier_pillar["mode"] == supplier_pillar["provenance"] == "fixture"
    assert consumer_pillar["mode"] == consumer_pillar["provenance"] == "fixture"
    assert marketplace["mode"] not in REMAPPED_PROVENANCE
    assert supplier_pillar["mode"] not in REMAPPED_PROVENANCE
    assert consumer_pillar["mode"] not in REMAPPED_PROVENANCE
    assert "stale_evidence:marketplace" in row["blockers"]
    assert "stale_evidence:marketplace" in report["blockers"]
    assert "stale_evidence:supplier" not in row["blockers"]
    assert "stale_evidence:consumer" not in row["blockers"]
    assert set(row["pillars"]) == {"marketplace", "supplier", "consumer"}
    assert report["governor"]["live_go"] is False
    _assert_not_authorized(report)


def test_missing_evidence_mode_is_omitted_not_invented():
    market = _strip_key(load("absent_observed_at_marketplace_report.json"), "evidence_mode")
    supplier = _strip_key(load("absent_observed_at_supplier_report.json"), "evidence_mode")
    consumer = _strip_key(load("absent_observed_at_consumer_report.json"), "evidence_mode")
    assert "evidence_mode" not in json.dumps(market)
    assert "evidence_mode" not in json.dumps(supplier)
    assert "evidence_mode" not in json.dumps(consumer)
    report = build_commerce_operations_cycle(market, supplier, consumer).to_dict()
    row = report["ranking"]["candidates"][0]
    for name, pillar in row["pillars"].items():
        assert pillar["mode"] == pillar["provenance"], name
        assert pillar["mode"] not in INVENTED_PROVENANCE, name
        assert pillar["provenance"] not in INVENTED_PROVENANCE, name
        assert pillar["mode"] in {"", "unavailable", "missing"}, name
        assert "observed_at" not in pillar, name
    for section_name in ("marketplace", "supplier", "consumer_attention"):
        mode = report[section_name].get("evidence_mode")
        assert mode not in INVENTED_PROVENANCE
    assert report["synthesis"]["confidence_grade"] != "A_live_validated"
    assert report["confidence_claim"] == "not_live_validated"
    _assert_not_authorized(report)


def test_partial_and_simulated_confidence_cannot_authorize_launch():
    simulated = load("evidence_mode_pass_through.json")["simulated"]
    expected = build_product_opportunity_synthesis(
        simulated["marketplace"], simulated["supplier"], simulated["consumer"]
    ).to_dict()
    report = build_commerce_operations_cycle(
        simulated["marketplace"], simulated["supplier"], simulated["consumer"]
    ).to_dict()
    assert report["confidence_claim"] == "not_live_validated"
    assert report["synthesis"]["confidence_grade"] == expected["confidence_grade"]
    assert expected["confidence_grade"] != "A_live_validated"
    assert report["client_safe_projection"]["confidence_grade"] == expected["confidence_grade"]
    assert report["client_safe_projection"]["confidence_claim"] == "not_live_validated"
    _assert_not_authorized(report)

    partial_expected = build_product_opportunity_synthesis(simulated["marketplace"], None, None).to_dict()
    partial = build_commerce_operations_cycle(simulated["marketplace"], None, None).to_dict()
    assert partial["confidence_claim"] == "not_live_validated"
    assert partial["synthesis"]["confidence_grade"] == partial_expected["confidence_grade"]
    assert partial["synthesis"]["confidence_grade"] in {"C_fixture_or_partial", "D_low_confidence", "F_reject_or_missing"}
    assert partial["synthesis"]["confidence_grade"] != "A_live_validated"
    assert partial["client_safe_projection"]["confidence_grade"] == partial_expected["confidence_grade"]
    _assert_not_authorized(partial)


def test_partial_stage_recovery_keeps_later_stages_and_projection():
    _market, supplier, consumer = pillars()
    reports = (
        cycle(live_requested=True).to_dict(),
        build_commerce_operations_cycle(None, None, None).to_dict(),
        build_commerce_operations_cycle(
            load("malformed_nested_non_object_marketplace.json"),
            supplier,
            consumer,
        ).to_dict(),
    )
    later = ("trustos", "governor", "approval_ledger", "launch_draft_readiness", "site_draft_readiness", "client_workspace")
    for report in reports:
        assert list(report["stages"]) == list(STAGE_ORDER)
        for name in STAGE_ORDER:
            _assert_uniform_stage(report[name], blockers_alias=True)
            _assert_uniform_stage(report["stages"][name])
        for name in later:
            assert name in report
            assert report[name].get("status")
            _assert_uniform_stage(report[name], blockers_alias=True)
        assert report["overall_status"] != "go"
        assert report["governor"].get("live_go") is not True
        projection = report["client_safe_projection"]
        blob = json.dumps(projection).lower()
        for forbidden in ("api_key", "token", "password", "raw_payload", "raw_html", "<html", "sk-", "authorization"):
            assert forbidden not in blob
        assert set(projection) == CLIENT_SAFE_PROJECTION_KEYS
        _assert_not_authorized(report)


def _batch_pack(name: str):
    if name == "default":
        return pillars()
    if name == "similar":
        return (
            load("similar_titles_market_report.json"),
            load("similar_titles_supplier_report.json"),
            load("similar_titles_consumer_report.json"),
        )
    if name == "labeled":
        return (
            load("labeled_marketplace_report.json"),
            load("labeled_supplier_report.json"),
            load("labeled_attention_report.json"),
        )
    raise AssertionError(f"unknown batch pack {name}")


def test_deterministic_batch_replay_does_not_cross_contaminate():
    names = ("default", "similar", "labeled")
    first_dumps: dict[str, str] = {}
    first_ids: dict[str, set[str]] = {}
    for name in names:
        report = build_commerce_operations_cycle(*_batch_pack(name)).to_dict()
        first_dumps[name] = _dump(report)
        first_ids[name] = {item["candidate_id"] for item in report["ranking"]["candidates"]}
        _assert_never_live_go(report)
        _assert_no_identity_authority(report)
    assert first_ids["default"].isdisjoint(first_ids["similar"])
    assert first_ids["default"].isdisjoint(first_ids["labeled"])
    assert first_ids["similar"].isdisjoint(first_ids["labeled"])
    for name in names:
        second = build_commerce_operations_cycle(*_batch_pack(name)).to_dict()
        assert _dump(second) == first_dumps[name]
        second_ids = {item["candidate_id"] for item in second["ranking"]["candidates"]}
        assert second_ids == first_ids[name]
        leaked = set().union(*(ids for other, ids in first_ids.items() if other != name))
        blob = first_dumps[name]
        for candidate_id in leaked:
            assert candidate_id not in blob
            assert candidate_id not in _dump(second)
        _assert_not_authorized(second)
