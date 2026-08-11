from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.commerce import evaluate_input, load_evaluation_input

FIXTURE = Path(__file__).parents[1] / "fixtures" / "commerce_evaluation"


def test_cli_json_from_artifact(capsys):
    from scripts.evaluate_commerce_run import main

    assert main(["--artifact", str(FIXTURE), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["framework_version"] == "commerce-evaluation-v1"
    assert report["overall"]["run_quality"] == "medium"


def test_cli_markdown_contains_engine_table(capsys):
    from scripts.evaluate_commerce_run import main

    assert main(["--artifact", str(FIXTURE), "--markdown"]) == 0
    output = capsys.readouterr().out
    assert "Commerce Intelligence Evaluation Report" in output
    assert "supplier_evidence" in output
    assert "competition_intelligence" in output


def test_cli_writes_report_only_when_output_is_explicit(tmp_path, capsys):
    from scripts.evaluate_commerce_run import main

    target = tmp_path / "evaluation_report.json"
    assert main(["--artifact", str(FIXTURE), "--json", "--output", str(target)]) == 0
    assert target.is_file()
    assert capsys.readouterr().out == ""


def test_cli_writes_canonical_evaluation_events_only_when_requested(tmp_path, capsys):
    from scripts.evaluate_commerce_run import main

    event_target = tmp_path / "evaluation-events.jsonl"
    assert main(["--artifact", str(FIXTURE), "--json", "--write-evaluation-events", str(event_target)]) == 0
    lines = event_target.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 7
    assert json.loads(lines[-1])["event_type"] == "commerce_evaluation_completed"
    assert json.loads(capsys.readouterr().out)["evaluation_event_count"] == 7


def test_cli_compares_two_runs(capsys):
    from scripts.evaluate_commerce_run import main

    assert main(["--run-a", str(FIXTURE), "--run-b", str(FIXTURE), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["comparison"]["ranking_stability"] == 1.0


def test_cli_accepts_replay_alias(capsys):
    from scripts.evaluate_commerce_run import main

    assert main(["--replay", str(FIXTURE / "events.jsonl"), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["input_kind"] == "replay"
    assert report["event_count"] == 8


def test_jsonl_malformed_rows_are_reported(tmp_path):
    source = tmp_path / "events.jsonl"
    source.write_text((FIXTURE / "events.jsonl").read_text(encoding="utf-8") + "not-json\n", encoding="utf-8")
    report = evaluate_input(load_evaluation_input(source, source="jsonl"))
    assert "malformed_jsonl_row:9" in report.warnings
    assert report.event_count == 8


def test_api_route_is_get_only():
    from api.routes.commerce_evaluations import router

    assert {method for route in router.routes for method in route.methods} == {"GET"}


def test_api_evaluation_reads_configured_artifact(monkeypatch, tmp_path):
    import api.routes.commerce_evaluations as evaluation_routes

    # The API deliberately permits only server-configured paths beneath its
    # artifact root. Keep the test within that contract by replacing the
    # configured root with a temporary server artifact directory.
    root = Path(tmp_path)
    target = root / "events.jsonl"
    target.write_text((FIXTURE / "events.jsonl").read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(evaluation_routes, "ARTIFACTS", root)
    monkeypatch.setenv("MARKETOS_EVENT_READ_JSONL_PATH", str(target))
    report = evaluation_routes.evaluation()
    assert report["framework_version"] == "commerce-evaluation-v1"
    assert report["event_count"] == 8


def test_api_evaluation_fails_closed_without_config(monkeypatch):
    from api.routes.commerce_evaluations import evaluation

    monkeypatch.delenv("MARKETOS_EVENT_READ_JSONL_PATH", raising=False)
    report = evaluation()
    assert report["status"] == "blocked"
    assert report["read_only"] is True


def test_api_rejects_configured_path_outside_artifacts(monkeypatch, tmp_path):
    from api.routes.commerce_evaluations import evaluation

    monkeypatch.setenv("MARKETOS_EVENT_READ_JSONL_PATH", str(tmp_path / "events.jsonl"))
    report = evaluation()
    assert report["status"] == "blocked"


def test_api_readiness_contains_no_secret_values(monkeypatch):
    from api.routes.commerce_evaluations import evaluation_readiness

    monkeypatch.setenv("MARKETOS_EVENT_READ_JSONL_PATH", str(FIXTURE / "events.jsonl"))
    report = evaluation_readiness()
    encoded = json.dumps(report)
    assert "SERVICE_ROLE" not in encoded
    assert report["write_methods"] == []


def test_api_compare_requires_server_config(monkeypatch):
    from api.routes.commerce_evaluations import evaluation_compare

    monkeypatch.delenv("MARKETOS_EVALUATION_BASELINE_JSONL_PATH", raising=False)
    monkeypatch.delenv("MARKETOS_EVALUATION_CURRENT_JSONL_PATH", raising=False)
    assert evaluation_compare()["status"] == "blocked"


@pytest.mark.parametrize("source_flag", ["--artifact", "--workspace"])
def test_cli_source_aliases_are_supported(source_flag, capsys):
    from scripts.evaluate_commerce_run import main

    assert main([source_flag, str(FIXTURE), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["event_count"] == 8
