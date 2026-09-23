"""Tests for scripts/ai/validate_business_opportunity_playbook.py -- the
deterministic operator validator for the business opportunity playbook and
its synthetic fixtures. Exercises the shipped doc/fixtures (must pass) and
scratch-mutated copies (must fail for the right reason), never the shared
fixtures used by tests/contracts/test_business_opportunity_playbook.py.
"""
from __future__ import annotations

import json

from scripts.ai import validate_business_opportunity_playbook as validator


def test_shipped_playbook_and_fixtures_pass_validation():
    result = validator.run_validation()
    assert result["valid"] is True, result["errors"]
    assert result["fixture_count"] == 6
    assert len(result["stable_hash"]) == 64


def test_validation_is_deterministic():
    first = validator.run_validation()
    second = validator.run_validation()
    assert first == second


def test_offering_kind_outside_schema_is_rejected():
    data = {
        "scenario_id": "s", "offering_kind": "bogus", "opportunity_archetype": "ecommerce_goods",
        "candidate_id": "fixture-candidate-x", "workspace_id": "fixture-workspace-methodology",
        "geography": "g", "language": "en", "claims": [], "evidence": [],
        "economics": {"currency": "USD"}, "blockers": ["b"],
        "experiment": {"decision": "d", "evidence_class": "planned", "stop_rule": "s"},
        "expected": {"status": "blocked", "fatal_gate": "reachable_buyer_missing"},
    }
    errors = validator.validate_fixture("s", data, json.dumps(data))
    assert any("offering_kind" in error for error in errors)


def test_evidence_dimension_outside_eight_lenses_is_rejected():
    data = {
        "scenario_id": "s", "offering_kind": "goods", "opportunity_archetype": "ecommerce_goods",
        "candidate_id": "fixture-candidate-x", "workspace_id": "fixture-workspace-methodology",
        "geography": "g", "language": "en", "claims": [],
        "evidence": [{"id": "e1", "dimension": "not_a_lens", "evidence_class": "manual", "source_ref": "fixture://x"}],
        "economics": {"currency": "USD"}, "blockers": ["b"],
        "experiment": {"decision": "d", "evidence_class": "planned", "stop_rule": "s"},
        "expected": {"status": "blocked", "fatal_gate": "reachable_buyer_missing"},
    }
    errors = validator.validate_fixture("s", data, json.dumps(data))
    assert any("dimension" in error for error in errors)


def test_live_evidence_class_is_rejected_in_an_offline_fixture():
    data = {
        "scenario_id": "s", "offering_kind": "goods", "opportunity_archetype": "ecommerce_goods",
        "candidate_id": "fixture-candidate-x", "workspace_id": "fixture-workspace-methodology",
        "geography": "g", "language": "en",
        "claims": [{"id": "c1", "taxonomy": "fact", "statement": "ok", "evidence_class": "live", "source_ref": "fixture://x"}],
        "evidence": [], "economics": {"currency": "USD"}, "blockers": ["b"],
        "experiment": {"decision": "d", "evidence_class": "planned", "stop_rule": "s"},
        "expected": {"status": "blocked", "fatal_gate": "reachable_buyer_missing"},
    }
    errors = validator.validate_fixture("s", data, json.dumps(data))
    assert any("live evidence_class" in error for error in errors)


def test_explicit_zero_economics_value_is_rejected_not_missing():
    data = {
        "scenario_id": "s", "offering_kind": "goods", "opportunity_archetype": "ecommerce_goods",
        "candidate_id": "fixture-candidate-x", "workspace_id": "fixture-workspace-methodology",
        "geography": "g", "language": "en", "claims": [], "evidence": [],
        "economics": {"currency": "USD", "duty": 0}, "blockers": ["b"],
        "experiment": {"decision": "d", "evidence_class": "planned", "stop_rule": "s"},
        "expected": {"status": "blocked", "fatal_gate": "reachable_buyer_missing"},
    }
    errors = validator.validate_fixture("s", data, json.dumps(data))
    assert any("explicit zero" in error for error in errors)


def test_undocumented_economics_token_is_rejected():
    data = {
        "scenario_id": "s", "offering_kind": "goods", "opportunity_archetype": "ecommerce_goods",
        "candidate_id": "fixture-candidate-x", "workspace_id": "fixture-workspace-methodology",
        "geography": "g", "language": "en", "claims": [], "evidence": [],
        "economics": {"currency": "USD", "duty": "totally_free"}, "blockers": ["b"],
        "experiment": {"decision": "d", "evidence_class": "planned", "stop_rule": "s"},
        "expected": {"status": "blocked", "fatal_gate": "reachable_buyer_missing"},
    }
    errors = validator.validate_fixture("s", data, json.dumps(data))
    assert any("undocumented status token" in error for error in errors)


def test_an_explicit_nonzero_quoted_number_is_accepted():
    data = {
        "scenario_id": "s", "offering_kind": "goods", "opportunity_archetype": "ecommerce_goods",
        "candidate_id": "fixture-candidate-x", "workspace_id": "fixture-workspace-methodology",
        "geography": "g", "language": "en", "claims": [], "evidence": [],
        "economics": {"currency": "USD", "duty": "12.5"}, "blockers": ["b"],
        "experiment": {"decision": "d", "evidence_class": "planned", "stop_rule": "s"},
        "expected": {"status": "blocked", "fatal_gate": "reachable_buyer_missing"},
    }
    errors = validator.validate_fixture("s", data, json.dumps(data))
    assert not any("economics.duty" in error for error in errors)


def test_prohibited_claim_wording_is_rejected():
    data = {
        "scenario_id": "s", "offering_kind": "goods", "opportunity_archetype": "ecommerce_goods",
        "candidate_id": "fixture-candidate-x", "workspace_id": "fixture-workspace-methodology",
        "geography": "g", "language": "en",
        "claims": [{"id": "c1", "taxonomy": "fact", "statement": "Customers want this.", "evidence_class": "manual", "source_ref": "fixture://x"}],
        "evidence": [], "economics": {"currency": "USD"}, "blockers": ["b"],
        "experiment": {"decision": "d", "evidence_class": "planned", "stop_rule": "s"},
        "expected": {"status": "blocked", "fatal_gate": "reachable_buyer_missing"},
    }
    errors = validator.validate_fixture("s", data, json.dumps(data))
    assert any("prohibited wording" in error for error in errors)


def test_secret_shaped_payload_in_raw_text_is_rejected():
    data = {
        "scenario_id": "s", "offering_kind": "goods", "opportunity_archetype": "ecommerce_goods",
        "candidate_id": "fixture-candidate-x", "workspace_id": "fixture-workspace-methodology",
        "geography": "g", "language": "en", "claims": [], "evidence": [],
        "economics": {"currency": "USD"}, "blockers": ["b"],
        "experiment": {"decision": "d", "evidence_class": "planned", "stop_rule": "s"},
        "expected": {"status": "blocked", "fatal_gate": "reachable_buyer_missing"},
    }
    raw = json.dumps(data) + " password="
    errors = validator.validate_fixture("s", data, raw)
    assert any("forbidden_payload_marker" in error for error in errors)


def test_scoring_authority_token_in_raw_text_is_rejected():
    data = {
        "scenario_id": "s", "offering_kind": "goods", "opportunity_archetype": "ecommerce_goods",
        "candidate_id": "fixture-candidate-x", "workspace_id": "fixture-workspace-methodology",
        "geography": "g", "language": "en", "claims": [], "evidence": [],
        "economics": {"currency": "USD"}, "blockers": ["b"],
        "experiment": {"decision": "d", "evidence_class": "planned", "stop_rule": "s"},
        "expected": {"status": "blocked", "fatal_gate": "reachable_buyer_missing"},
    }
    raw = json.dumps(data) + " score_this_candidate"
    errors = validator.validate_fixture("s", data, raw)
    assert any("forbidden_authority_marker" in error for error in errors)


def test_unrecognized_fatal_gate_is_rejected():
    data = {
        "scenario_id": "s", "offering_kind": "goods", "opportunity_archetype": "ecommerce_goods",
        "candidate_id": "fixture-candidate-x", "workspace_id": "fixture-workspace-methodology",
        "geography": "g", "language": "en", "claims": [], "evidence": [],
        "economics": {"currency": "USD"}, "blockers": ["b"],
        "experiment": {"decision": "d", "evidence_class": "planned", "stop_rule": "s"},
        "expected": {"status": "blocked", "fatal_gate": "made_up_gate"},
    }
    errors = validator.validate_fixture("s", data, json.dumps(data))
    assert any("fatal_gate" in error for error in errors)


def test_missing_required_key_is_reported_and_short_circuits():
    errors = validator.validate_fixture("s", {"scenario_id": "s"}, "{}")
    assert any("missing keys" in error for error in errors)


def test_playbook_doc_mode_removal_is_caught(tmp_path):
    text = validator.DEFAULT_PLAYBOOK.read_text(encoding="utf-8")
    broken = tmp_path / "playbook.md"
    broken.write_text(text.replace("### Compare\n", ""), encoding="utf-8")
    errors = validator.validate_playbook_doc(broken)
    assert any("modes_mismatch" in error for error in errors)


def test_playbook_doc_fatal_gate_row_removal_is_caught(tmp_path):
    text = validator.DEFAULT_PLAYBOOK.read_text(encoding="utf-8")
    row = "| Unauthorized external action | Keep the output planned or simulated and route through Approval Ledger. |\n"
    assert row in text
    broken = tmp_path / "playbook.md"
    broken.write_text(text.replace(row, ""), encoding="utf-8")
    errors = validator.validate_playbook_doc(broken)
    assert any("fatal_gate_row_count" in error for error in errors)


def test_missing_playbook_file_is_reported():
    errors = validator.validate_playbook_doc(validator.ROOT / "does" / "not" / "exist.md")
    assert any("playbook_missing" in error for error in errors)


def test_render_json_and_markdown_outputs_are_stable():
    result = validator.run_validation()
    json_first = validator.render_json_or_markdown(result, markdown=False, title="t")
    json_second = validator.render_json_or_markdown(result, markdown=False, title="t")
    assert json_first == json_second
    markdown = validator.render_json_or_markdown(result, markdown=True, title="t")
    assert markdown.startswith("# t")


def test_cli_exit_code_reflects_validity(capsys):
    assert validator.main([]) == 0
    assert validator.main(["--json"]) == 0
    capsys.readouterr()


def test_cli_rejects_both_json_and_markdown():
    import pytest

    with pytest.raises(SystemExit):
        validator.main(["--json", "--markdown"])
