from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.run_product_opportunity_synthesis import main

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "opportunity_synthesis"


def test_default_json_is_deterministic(capsys):
    main(["--json"])
    first = json.loads(capsys.readouterr().out)
    main(["--json"])
    second = json.loads(capsys.readouterr().out)
    first["generated_at"] = second["generated_at"]
    assert first == second


def test_fixture_inputs_produce_three_pillar_report(capsys):
    main(["--marketplace-trend-report", str(FIXTURES / "marketplace_trend_report.json"), "--supplier-feasibility-report", str(FIXTURES / "supplier_feasibility_report.json"), "--consumer-attention-report", str(FIXTURES / "consumer_attention_report.json"), "--json"])
    report = json.loads(capsys.readouterr().out)
    assert report["candidate_count"] == 2
    assert report["source_reports"]["consumer_attention"] == "supplied"


def test_markdown_has_client_sections(capsys):
    main(["--markdown"])
    output = capsys.readouterr().out
    assert "Product Opportunity Synthesis" in output
    assert "Opportunity Scorecard" in output
    assert "14-Day Validation Plan" in output


def test_output_writes_only_sanitized_pack(tmp_path, capsys):
    main(["--output", str(tmp_path), "--json"])
    capsys.readouterr()
    assert {path.name for path in tmp_path.iterdir()} == {"opportunity_synthesis_report.json", "opportunity_synthesis_report.md", "client_action_checklist.md", "operator_decision_summary.json"}
    text = " ".join(path.read_text(encoding="utf8") for path in tmp_path.iterdir())
    assert "Bearer " not in text
    assert "CJ_API_KEY" not in text
    assert "read_only" in text


def test_client_action_checklist_is_generated(tmp_path, capsys):
    main(["--output", str(tmp_path), "--json"])
    capsys.readouterr()
    checklist = (tmp_path / "client_action_checklist.md").read_text(encoding="utf8")
    assert "Confirm the evidence mode" in checklist
    assert "Approve or reject" in checklist


def test_operator_summary_is_redacted(tmp_path, capsys):
    main(["--output", str(tmp_path), "--json"])
    capsys.readouterr()
    summary = json.loads((tmp_path / "operator_decision_summary.json").read_text(encoding="utf8"))
    assert summary["read_only"] is True
    assert "secret" not in json.dumps(summary).lower()


def test_json_and_markdown_are_exclusive():
    with pytest.raises(SystemExit):
        main(["--json", "--markdown"])


def test_missing_input_is_reported(capsys, tmp_path):
    with pytest.raises(SystemExit):
        main(["--marketplace-trend-report", str(tmp_path / "missing.json"), "--json"])
    assert "does not exist" in capsys.readouterr().err


def test_path_traversal_is_rejected(capsys):
    with pytest.raises(SystemExit):
        main(["--consumer-attention-report", "..\\secret.json", "--json"])
    assert "traversal" in capsys.readouterr().err


@pytest.mark.parametrize("name", ["marketplace_trend_report.json", "supplier_feasibility_report.json", "consumer_attention_report.json"])
def test_each_input_can_be_supplied_independently(name, capsys):
    flag = {"marketplace_trend_report.json": "--marketplace-trend-report", "supplier_feasibility_report.json": "--supplier-feasibility-report", "consumer_attention_report.json": "--consumer-attention-report"}[name]
    main([flag, str(FIXTURES / name), "--json"])
    report = json.loads(capsys.readouterr().out)
    assert report["candidate_count"] >= 1


@pytest.mark.parametrize("flag", ["--marketplace-trend-report", "--supplier-feasibility-report", "--consumer-attention-report", "--product-validation-report", "--client-context"])
def test_non_json_input_is_rejected(flag, capsys, tmp_path):
    path = tmp_path / "input.txt"
    path.write_text("not json", encoding="utf8")
    with pytest.raises(SystemExit):
        main([flag, str(path), "--json"])
    assert "JSON" in capsys.readouterr().err or "json" in capsys.readouterr().err


def test_product_validation_context_is_accepted(capsys):
    main(["--product-validation-report", str(FIXTURES / "marketplace_trend_report.json"), "--json"])
    report = json.loads(capsys.readouterr().out)
    assert report["source_reports"]["product_validation"] == "supplied"


def test_client_context_is_accepted(capsys, tmp_path):
    context = tmp_path / "context.json"
    context.write_text(json.dumps({"client_name": "Sanitized Demo", "sector": "home"}), encoding="utf8")
    main(["--client-context", str(context), "--json"])
    report = json.loads(capsys.readouterr().out)
    assert report["read_only"] is True


def test_default_has_no_network_flags(capsys):
    main(["--json"])
    report = json.loads(capsys.readouterr().out)
    assert report["network_calls"] is False
    assert report["mutated"] is False


def test_markdown_disclaims_launch_authority(capsys):
    main(["--markdown"])
    assert "not launch authorization" in capsys.readouterr().out


@pytest.mark.parametrize("index", range(10))
def test_default_report_has_deterministic_plan(index, capsys):
    main(["--json"])
    report = json.loads(capsys.readouterr().out)
    assert len(report["fourteen_day_validation_plan"]) == 8
    assert all(day["read_only"] for day in report["fourteen_day_validation_plan"])
