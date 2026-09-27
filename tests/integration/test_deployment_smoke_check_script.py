import json
from pathlib import Path

import pytest

from scripts import deployment_smoke_check as smoke_cli
from scripts.deployment_smoke_check import build_report

ROOT = Path(__file__).resolve().parents[2]


def test_missing_environment_is_partial_and_never_prints_values():
    report = build_report(environ={})
    assert report["status"] == "partial"
    assert report["network_calls"] is False
    assert report["mutated"] is False
    assert "SUPABASE_SERVICE_ROLE_KEY" not in str(report)


def test_safe_environment_passes_gates_and_artifact_paths():
    values = {
        "ALLOWED_ORIGINS": "http://localhost:5173",
        "MARKETOS_MVP_MODE": "1",
        "MARKETOS_EVENT_READ_JSONL_PATH": "artifacts/read.jsonl",
        "MARKETOS_EVENT_WRITE_JSONL_PATH": "artifacts/write.jsonl",
            "MARKETOS_PUBLIC_SIGNAL_CACHE_DIR": "artifacts/cache",
            "MARKETOS_PUBLIC_COMMERCE_RUNS": "0",
            "MARKETOS_SUPABASE_CANONICAL_EVENTS": "0",
            "VITE_API_BASE_URL": "http://localhost:8000",
            "VITE_POSTHOG_KEY": "disabled-in-test",
            "VITE_POSTHOG_HOST": "https://app.posthog.com",
        }
    report = build_report(environ=values)
    assert report["status"] == "passed"
    assert all(item["status"] == "passed" for item in report["checks"] if item["name"] in {"default_off_gates", "artifact_paths", "frontend_secret_names"})


def test_paths_outside_artifacts_fail_closed():
    report = build_report(environ={"MARKETOS_EVENT_READ_JSONL_PATH": "state/events.jsonl"})
    path_check = next(item for item in report["checks"] if item["name"] == "artifact_paths")
    assert path_check["status"] == "failed"
    assert report["status"] == "failed"


@pytest.mark.parametrize(("status", "expected_exit"), [("passed", 0), ("partial", 1), ("failed", 1)])
def test_smoke_cli_exit_code_tracks_readiness_status(monkeypatch, capsys, status, expected_exit):
    monkeypatch.setattr(
        smoke_cli,
        "build_report",
        lambda **_: {"status": status, "network_calls": False, "mutated": False, "checks": [], "next_actions": []},
    )
    assert smoke_cli.main(["--local", "--json"]) == expected_exit
    assert json.loads(capsys.readouterr().out)["status"] == status
