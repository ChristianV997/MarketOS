"""Contract tests for the existing commerce-operations cycle as a release packet.

The packet is ``build_commerce_operations_cycle(...).to_dict()``. This module
does not add a second schema, builder, scorer, fingerprint, or source_family.
It imports the existing cycle and CLI and asserts the documented operator shape.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from evaluation.commerce.commerce_operations_cycle import (
    GENERATED_AT,
    REPORT_VERSION,
    STAGE_ORDER,
    build_commerce_operations_cycle,
    reject_unsafe_input,
)
from scripts.run_commerce_operations_cycle import main

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "commerce_operations"
SYNTHESIS_FIXTURES = ROOT / "tests" / "fixtures" / "opportunity_synthesis"
CLI = ROOT / "scripts" / "run_commerce_operations_cycle.py"
CYCLE_SOURCE = ROOT / "evaluation" / "commerce" / "commerce_operations_cycle.py"
CLI_SOURCE = ROOT / "scripts" / "run_commerce_operations_cycle.py"

REQUIRED_TOP_LEVEL_KEYS = (
    "report_version",
    "generated_at",
    "cycle_mode",
    "overall_status",
    "evidence_class",
    "confidence_claim",
    "live_requested",
    "live_validated",
    "marketplace",
    "supplier",
    "consumer_attention",
    "synthesis",
    "ranking",
    "product_validation",
    "trustos",
    "governor",
    "approval_ledger",
    "launch_draft_readiness",
    "site_draft_readiness",
    "client_workspace",
    "client_safe_projection",
    "stages",
    "blockers",
    "evidence_required",
    "approvals_required",
    "next_best_action",
    "safety_summary",
    "read_only",
    "network_calls",
    "mutated",
    "artifacts_written",
)
CLIENT_SAFE_PROJECTION_KEYS = (
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
)
OUTPUT_FILENAMES = {
    "commerce_operations_cycle_report.json",
    "commerce_operations_cycle_report.md",
    "client_safe_projection.json",
}
FORBIDDEN_OUTPUT_NAMES = {
    "launch_draft_pack.json",
    "site_draft_pack.json",
    "launch_pack.json",
    "site_pack.json",
}
FORBIDDEN_SOURCE_TOKENS = ("rank_opportunities", "fingerprint", "source_family")
SECRET_SUBSTRINGS = (
    "api_key",
    "token",
    "password",
    "raw_payload",
    "raw_html",
    "<html",
    "sk-",
    "authorization",
    "synthetic-secret-must-not-be-imported",
    "bearer synthetic-token-must-not-be-imported",
)


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
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_required_top_level_keys_present_on_default_to_dict():
    report = cycle().to_dict()
    missing = [key for key in REQUIRED_TOP_LEVEL_KEYS if key not in report]
    assert missing == []
    assert report["report_version"] == REPORT_VERSION == "commerce-operations-cycle-v1"
    assert report["generated_at"] == GENERATED_AT == "offline-deterministic"
    assert list(report["stages"]) == list(STAGE_ORDER)


def test_packet_is_existing_to_dict_not_a_second_schema():
    built = cycle()
    packet = built.to_dict()
    again = built.to_dict()
    assert packet == again
    assert packet["client_safe_projection"]["report_version"] == packet["report_version"]
    assert packet["client_safe_projection"]["generated_at"] == packet["generated_at"]
    assert packet["client_safe_projection"]["overall_status"] == packet["overall_status"]
    assert packet["client_safe_projection"]["next_best_action"] == packet["next_best_action"]
    assert packet["client_safe_projection"]["top_candidate_id"] == packet["synthesis"]["top_candidate_id"]
    assert packet["client_safe_projection"]["overall_recommendation"] == packet["synthesis"]["overall_recommendation"]
    source = CYCLE_SOURCE.read_text(encoding="utf8")
    assert "def to_dict(self)" in source
    assert "def _client_safe_projection(" in source
    assert "build_release_packet" not in source
    assert "class ReleasePacket" not in source


def test_client_safe_projection_present_and_secret_free():
    report = cycle().to_dict()
    projection = report["client_safe_projection"]
    assert set(projection) == set(CLIENT_SAFE_PROJECTION_KEYS)
    assert projection["evidence_class"] == "client_safe_projection"
    assert projection["confidence_claim"] == "not_live_validated"
    assert projection["live_validated"] is False
    assert projection["launch_authorized"] is False
    assert projection["publishing_authorized"] is False
    blob = json.dumps(projection).lower()
    for forbidden in SECRET_SUBSTRINGS:
        assert forbidden not in blob


def test_malformed_and_missing_fields_fail_closed_without_inventing_scores():
    with pytest.raises(ValueError, match="malformed"):
        build_commerce_operations_cycle(["not", "an", "object"], None, None)

    market, _, consumer = pillars()
    missing = build_commerce_operations_cycle(market, None, consumer).to_dict()
    assert "supplier_pillar_missing" in missing["blockers"]
    assert missing["supplier"]["supplied"] is False
    assert missing["confidence_claim"] == "not_live_validated"
    assert missing["live_validated"] is False
    assert missing["synthesis"]["confidence_grade"] != "A_live_validated"
    assert missing["governor"].get("live_go") is not True

    empty = build_commerce_operations_cycle(
        load("empty_marketplace_report.json"),
        load("empty_supplier_report.json"),
        load("empty_consumer_report.json"),
    ).to_dict()
    assert empty["marketplace"]["status"] == "unavailable"
    assert "marketplace_candidates_missing" in empty["blockers"]
    assert empty["confidence_claim"] == "not_live_validated"
    assert empty["live_validated"] is False
    assert empty["synthesis"]["confidence_grade"] != "A_live_validated"
    assert empty["governor"].get("live_go") is not True

    cli = run_cli("--marketplace-trend-report", str(FIXTURES / "malformed_cycle_input.json"), "--json")
    assert cli.returncode == 2
    assert "A_live_validated" not in cli.stdout
    assert "combined_opportunity_score" not in cli.stdout


def test_nested_secret_like_rejected_and_not_echoed():
    payload = load("nested_secret_report.json")
    assert payload["imports"][0]["credentials"]["api_key"] == "synthetic-secret-must-not-be-imported"
    with pytest.raises(ValueError, match="secret-like or raw payload"):
        reject_unsafe_input(payload, label="fixture")
    with pytest.raises(ValueError, match="secret-like or raw payload"):
        build_commerce_operations_cycle(payload, None, None)
    try:
        build_commerce_operations_cycle(payload, None, None)
    except ValueError as exc:
        text = str(exc)
        assert "synthetic-secret-must-not-be-imported" not in text
        assert "api_key" not in text.lower() or "secret-like" in text

    result = run_cli("--marketplace-trend-report", str(FIXTURES / "nested_secret_report.json"), "--json")
    assert result.returncode == 2
    combined = result.stdout + result.stderr
    assert "synthetic-secret-must-not-be-imported" not in combined
    assert "hidden-provider-body" not in combined


def test_fixture_and_simulated_evidence_never_become_live_validated_at_cycle_layer():
    report = cycle().to_dict()
    assert report["confidence_claim"] == "not_live_validated"
    assert report["live_validated"] is False
    assert report["evidence_class"] == "not_live_validated"
    assert report["cycle_mode"] == "dry_run"
    assert report["overall_status"] == "plan_only"
    assert report["synthesis"]["confidence_grade"] != "A_live_validated"
    assert report["governor"].get("live_go") is False
    blob = json.dumps(report)
    assert '"confidence_claim": "A_live_validated"' not in blob
    assert '"confidence_claim": "live_validated"' not in blob
    assert report["marketplace"]["evidence_class"] == "fixture_evidence"
    assert report["ranking"]["confidence_claim"] == "not_live_validated"


def test_stale_evidence_named_when_fixture_sets_stale():
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


def test_absent_observed_at_omitted_generated_at_is_cycle_clock_not_freshness():
    market = load("absent_observed_at_marketplace_report.json")
    supplier = load("absent_observed_at_supplier_report.json")
    consumer = load("absent_observed_at_consumer_report.json")
    assert "observed_at" not in json.dumps(market)
    report = build_commerce_operations_cycle(market, supplier, consumer).to_dict()
    assert report["generated_at"] == "offline-deterministic"
    row = report["ranking"]["candidates"][0]
    for name, pillar in row["pillars"].items():
        assert "observed_at" not in pillar, name
        assert pillar.get("observed_at") != "deterministic"
        assert pillar.get("observed_at") != "offline-deterministic"
    assert "observed_at" not in json.dumps(row["pillars"])
    assert report["generated_at"] != row["pillars"]["marketplace"].get("observed_at")


def test_live_readonly_evidence_mode_stays_raw_never_observed():
    market = load("live_readonly_marketplace_report.json")
    supplier = load("live_readonly_supplier_report.json")
    consumer = load("live_readonly_attention_report.json")
    report = build_commerce_operations_cycle(market, supplier, consumer).to_dict()
    assert report["confidence_claim"] == "not_live_validated"
    assert report["live_validated"] is False
    assert report["governor"]["live_go"] is False
    assert report["synthesis"]["confidence_grade"] == "A_live_validated"
    row = report["ranking"]["candidates"][0]
    for name, pillar in row["pillars"].items():
        assert pillar["mode"] == "live_readonly", name
        assert pillar["provenance"] == "live_readonly", name
        assert pillar["provenance"] != "observed"
        assert pillar["mode"] != "observed"
    assert report["marketplace"]["evidence_mode"] == "live_readonly"
    assert report["supplier"]["evidence_mode"] == "live_readonly"
    assert report["consumer_attention"]["evidence_mode"] == "live_readonly"


def test_trustos_governor_blockers_visible_live_go_false():
    report = cycle().to_dict()
    assert report["governor"]["live_go"] is False
    assert report["trustos"]["professional_conclusion"] is False
    trustos_blockers = [item for item in report["blockers"] if str(item).startswith("trustos_")]
    governor_blockers = [item for item in report["blockers"] if str(item).startswith("governor_")]
    assert trustos_blockers
    assert governor_blockers
    decisions = {item.get("action"): item.get("decision") for item in report["trustos"].get("gates") or []}
    assert decisions.get("public_beta_launch") == "hard_block"
    assert report["approval_ledger"]["live_approval_granted"] is False


def test_cli_live_fail_closed_blocked():
    result = run_cli("--live", "--json")
    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert report["overall_status"] == "blocked"
    assert report["cycle_mode"] == "blocked"
    assert report["evidence_class"] == "blocked"
    assert "live_mode_requested" in report["blockers"]
    assert report["live_validated"] is False
    assert report["confidence_claim"] == "not_live_validated"
    assert report["governor"].get("live_go") is not True


def test_two_run_deterministic_serialization_of_to_dict_and_cli_json_stdout():
    first = cycle().to_dict()
    second = cycle().to_dict()
    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)

    cli_first = run_cli("--json")
    cli_second = run_cli("--json")
    assert cli_first.returncode == 0
    assert cli_second.returncode == 0
    assert cli_first.stdout == cli_second.stdout
    parsed = json.loads(cli_first.stdout)
    assert parsed == json.loads(cli_second.stdout)
    assert cli_first.stdout == json.dumps(parsed, indent=2, sort_keys=True) + "\n" or cli_first.stdout == json.dumps(parsed, indent=2, sort_keys=True)


def test_cli_output_writes_exactly_three_filenames_no_launch_site_packs(tmp_path, capsys):
    assert main(["--output", str(tmp_path), "--json"]) == 0
    capsys.readouterr()
    names = {path.name for path in tmp_path.iterdir()}
    assert names == OUTPUT_FILENAMES
    assert names.isdisjoint(FORBIDDEN_OUTPUT_NAMES)
    packet = json.loads((tmp_path / "commerce_operations_cycle_report.json").read_text(encoding="utf8"))
    projection = json.loads((tmp_path / "client_safe_projection.json").read_text(encoding="utf8"))
    assert projection == packet["client_safe_projection"]
    blob = json.dumps(projection).lower()
    for forbidden in SECRET_SUBSTRINGS:
        assert forbidden not in blob
    markdown = (tmp_path / "commerce_operations_cycle_report.md").read_text(encoding="utf8")
    assert "Commerce Operations Readiness Cycle" in markdown


def test_cycle_source_has_no_rank_opportunities_fingerprint_or_source_family():
    for path in (CYCLE_SOURCE, CLI_SOURCE):
        source = path.read_text(encoding="utf8")
        for token in FORBIDDEN_SOURCE_TOKENS:
            assert token not in source, f"{token} found in {path}"
        tree = ast.parse(source, filename=str(path))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                names.add(node.value)
            elif isinstance(node, ast.alias):
                names.add(node.name)
                if node.asname:
                    names.add(node.asname)
        for token in FORBIDDEN_SOURCE_TOKENS:
            assert token not in names, f"{token} found in AST of {path}"
    ranking = cycle().to_dict()["ranking"]
    assert "fingerprint" not in ranking
    for item in ranking["candidates"]:
        assert "fingerprint" not in item
        assert "source_family" not in json.dumps(item["pillars"])


def test_release_packet_tests_do_not_import_scoring_module():
    tree = ast.parse(Path(__file__).read_text(encoding="utf8"), filename=__file__)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            imported.update(alias.name for alias in node.names)
    assert all("opportunity_scoring" not in name for name in imported)
    cycle_source = CYCLE_SOURCE.read_text(encoding="utf8")
    assert "opportunity_scoring" not in cycle_source
    assert "rank_opportunities" not in cycle_source
