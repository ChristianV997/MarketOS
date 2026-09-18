"""Focused CLI tests for bounded commerce-operations cycle batch I/O.

This suite does not re-test the production cycle. It locks argparse batch
behavior on scripts/run_commerce_operations_cycle.py: one existing cycle per
job, no second scorer, packet type, or live provider path.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.run_commerce_operations_cycle import MAX_BATCH_JOBS, main

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "run_commerce_operations_cycle.py"
BATCH = ROOT / "tests" / "fixtures" / "commerce_operations" / "cli_batch"
CYCLE_OUTPUT_NAMES = {
    "commerce_operations_cycle_report.json",
    "commerce_operations_cycle_report.md",
    "client_safe_projection.json",
}
SECRET_NEEDLES = (
    "synthetic-secret-must-not-be-imported",
    "Bearer synthetic-token-must-not-be-imported",
    "reject-this-fixture",
    "hidden-provider-body",
    "<html",
)


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(CLI), *args], cwd=ROOT, text=True, capture_output=True, check=False)


def _combined(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout + result.stderr


def _assert_no_secret_leak(text: str) -> None:
    lowered = text.lower()
    for needle in SECRET_NEEDLES:
        assert needle.lower() not in lowered


def _collect_keys(value) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            keys.add(str(key).lower())
            keys |= _collect_keys(item)
    elif isinstance(value, list):
        for item in value:
            keys |= _collect_keys(item)
    return keys


def test_absent_manifest_still_emits_single_cycle_report():
    result = run_cli("--json")
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["report_version"] == "commerce-operations-cycle-v1"
    assert "jobs" not in payload
    assert payload["generated_at"] == "offline-deterministic"


def test_valid_manifest_admits_all_jobs():
    result = run_cli("--manifest", str(BATCH / "valid_manifest.json"), "--json")
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["report_version"] == "commerce-operations-cycle-batch-v1"
    assert payload["job_count"] == 2
    assert payload["admitted_count"] == 2
    assert payload["failed_count"] == 0
    assert [job["id"] for job in payload["jobs"]] == ["job-alpha", "job-beta"]
    for job in payload["jobs"]:
        assert job["status"] == "admitted"
        assert job["overall_status"]
        assert job["evidence_class"]
        assert isinstance(job["blockers"], list)


def test_malformed_json_manifest_exits_2():
    result = run_cli("--manifest", str(BATCH / "malformed_json_manifest.json"), "--json")
    assert result.returncode == 2
    assert "malformed" in result.stderr.lower()
    _assert_no_secret_leak(_combined(result))


def test_malformed_jobs_array_exits_2():
    result = run_cli("--manifest", str(BATCH / "malformed_jobs_not_list.json"), "--json")
    assert result.returncode == 2
    assert "jobs" in result.stderr.lower()


def test_missing_files_classified_unavailable():
    result = run_cli("--manifest", str(BATCH / "missing_file_manifest.json"), "--json")
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["admitted_count"] == 0
    assert payload["failed_count"] == 1
    job = payload["jobs"][0]
    assert job["id"] == "job-missing"
    assert job["status"] == "unavailable"
    assert job["overall_status"] == "unavailable"
    assert job["evidence_class"] == "unavailable"
    assert job["blockers"]


def test_duplicate_job_ids_fail_closed():
    result = run_cli("--manifest", str(BATCH / "duplicate_ids_manifest.json"), "--json")
    assert result.returncode == 2
    assert "duplicate" in result.stderr.lower()
    assert result.stdout == "" or "jobs" not in result.stdout


def test_partial_results_one_bad_job_one_good(tmp_path, capsys):
    assert main(["--manifest", str(BATCH / "partial_manifest.json"), "--output", str(tmp_path), "--json"]) == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed["admitted_count"] == 1
    assert printed["failed_count"] == 1
    by_id = {job["id"]: job for job in printed["jobs"]}
    assert by_id["job-good"]["status"] == "admitted"
    assert by_id["job-missing"]["status"] == "unavailable"
    names = {path.name for path in tmp_path.iterdir()}
    assert names == {"batch_summary.json", "job-good"}
    job_dir = tmp_path / "job-good"
    assert {path.name for path in job_dir.iterdir()} == CYCLE_OUTPUT_NAMES
    assert not (tmp_path / "job-missing").exists()
    summary = json.loads((tmp_path / "batch_summary.json").read_text(encoding="utf8"))
    assert summary == printed


def test_unsafe_job_is_blocked_without_aborting_rest(tmp_path, capsys):
    assert main(["--manifest", str(BATCH / "unsafe_job_manifest.json"), "--output", str(tmp_path), "--json"]) == 1
    captured = capsys.readouterr()
    printed = json.loads(captured.out)
    _assert_no_secret_leak(captured.out + captured.err)
    by_id = {job["id"]: job for job in printed["jobs"]}
    assert by_id["job-good"]["status"] == "admitted"
    assert by_id["job-secret"]["status"] == "blocked"
    assert "secret_like_or_unsafe_input" in by_id["job-secret"]["blockers"]
    blob = (tmp_path / "batch_summary.json").read_text(encoding="utf8").lower()
    job_blob = (tmp_path / "job-good" / "commerce_operations_cycle_report.json").read_text(encoding="utf8").lower()
    projection = (tmp_path / "job-good" / "client_safe_projection.json").read_text(encoding="utf8").lower()
    for text in (blob, job_blob, projection, captured.out.lower()):
        assert "synthetic-secret-must-not-be-imported" not in text
        assert "raw_payload" not in text
        assert "<html" not in text


def test_malformed_job_json_does_not_abort_rest():
    result = run_cli("--manifest", str(BATCH / "malformed_job_manifest.json"), "--json")
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    by_id = {job["id"]: job for job in payload["jobs"]}
    assert by_id["job-good"]["status"] == "admitted"
    assert by_id["job-malformed"]["status"] == "malformed"


def test_deterministic_replay_twice(tmp_path):
    first_dir = tmp_path / "run-a"
    second_dir = tmp_path / "run-b"
    first = run_cli("--manifest", str(BATCH / "valid_manifest.json"), "--output", str(first_dir), "--json")
    second = run_cli("--manifest", str(BATCH / "valid_manifest.json"), "--output", str(second_dir), "--json")
    assert first.returncode == 0
    assert second.returncode == 0
    assert first.stdout == second.stdout
    assert json.loads(first.stdout) == json.loads(second.stdout)
    first_summary = (first_dir / "batch_summary.json").read_bytes()
    second_summary = (second_dir / "batch_summary.json").read_bytes()
    assert first_summary == second_summary
    for job_id in ("job-alpha", "job-beta"):
        for name in CYCLE_OUTPUT_NAMES:
            assert (first_dir / job_id / name).read_bytes() == (second_dir / job_id / name).read_bytes()


def test_safe_output_omits_secret_html_and_raw_payload(tmp_path, capsys):
    assert main(["--manifest", str(BATCH / "unsafe_job_manifest.json"), "--output", str(tmp_path), "--json"]) == 1
    capsys.readouterr()
    for path in tmp_path.rglob("*"):
        if not path.is_file():
            continue
        blob = path.read_text(encoding="utf8")
        lowered = blob.lower()
        assert "synthetic-secret-must-not-be-imported" not in blob
        assert "<html" not in lowered
        assert "hidden-provider-body" not in blob
        assert "raw_payload" not in lowered
        assert "fingerprint" not in lowered
        assert "source_family" not in lowered
        assert path.name not in {"launch_draft_pack.json", "site_draft_pack.json", "packet.json"}
        if path.suffix == ".json":
            keys = _collect_keys(json.loads(path.read_text(encoding="utf8")))
            assert keys.isdisjoint({"api_key", "token", "html", "raw_payload", "raw_html"})


def test_live_with_manifest_fail_closes_blocked():
    result = run_cli("--manifest", str(BATCH / "valid_manifest.json"), "--live", "--json")
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["live_requested"] is True
    assert payload["admitted_count"] == 2
    for job in payload["jobs"]:
        assert job["status"] == "admitted"
        assert job["overall_status"] == "blocked"
        assert job["evidence_class"] == "blocked"
        assert "live_mode_requested" in job["blockers"]


def test_over_max_jobs_rejected(tmp_path):
    jobs = [
        {
            "id": f"job-{index}",
            "marketplace_trend_report": "tests/fixtures/commerce_operations/cli_batch/good_market.json",
            "supplier_feasibility_report": "tests/fixtures/commerce_operations/cli_batch/good_supplier.json",
            "consumer_attention_report": "tests/fixtures/commerce_operations/cli_batch/good_consumer.json",
        }
        for index in range(1, MAX_BATCH_JOBS + 2)
    ]
    manifest = tmp_path / "over_max.json"
    manifest.write_text(json.dumps({"jobs": jobs}), encoding="utf8")
    result = run_cli("--manifest", str(manifest), "--json")
    assert result.returncode == 2
    assert str(MAX_BATCH_JOBS) in result.stderr
    assert "maximum" in result.stderr.lower()


def test_manifest_path_traversal_rejected():
    result = run_cli("--manifest", "..\\secret.json", "--json")
    assert result.returncode == 2
    assert "traversal" in result.stderr
    _assert_no_secret_leak(_combined(result))


def test_job_path_traversal_classified_blocked_without_abort():
    result = run_cli("--manifest", str(BATCH / "traversal_job_manifest.json"), "--json")
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    job = payload["jobs"][0]
    assert job["status"] == "blocked"
    assert "path_traversal_blocked" in job["blockers"]


def test_manifest_secret_like_exits_2_and_does_not_echo():
    result = run_cli("--manifest", str(BATCH / "secret_like_manifest.json"), "--json")
    assert result.returncode == 2
    combined = _combined(result)
    assert "synthetic-secret-must-not-be-imported" not in combined
    assert "secret-like" in result.stderr.lower() or "raw payload" in result.stderr.lower()


def test_manifest_versus_report_flags_are_exclusive():
    result = run_cli(
        "--manifest",
        str(BATCH / "valid_manifest.json"),
        "--marketplace-trend-report",
        str(BATCH / "good_market.json"),
        "--json",
    )
    assert result.returncode == 2
    assert "manifest" in (result.stderr + result.stdout).lower()


def test_json_and_markdown_remain_exclusive_with_manifest():
    result = run_cli("--manifest", str(BATCH / "valid_manifest.json"), "--json", "--markdown")
    assert result.returncode == 2


def test_stdout_only_without_output(tmp_path, monkeypatch, capsys):
    manifest = tmp_path / "jobs.json"
    manifest.write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "id": "job-alpha",
                        "marketplace_trend_report": str(BATCH / "good_market.json"),
                        "supplier_feasibility_report": str(BATCH / "good_supplier.json"),
                        "consumer_attention_report": str(BATCH / "good_consumer.json"),
                    }
                ]
            }
        ),
        encoding="utf8",
    )
    monkeypatch.chdir(tmp_path)
    assert main(["--manifest", str(manifest), "--json"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["admitted_count"] == 1
    assert [path.name for path in tmp_path.iterdir()] == ["jobs.json"]


def test_output_writes_batch_summary_and_existing_filenames_only(tmp_path, capsys):
    assert main(["--manifest", str(BATCH / "valid_manifest.json"), "--output", str(tmp_path), "--json"]) == 0
    printed = json.loads(capsys.readouterr().out)
    names = {path.name for path in tmp_path.iterdir()}
    assert names == {"batch_summary.json", "job-alpha", "job-beta"}
    for job_id in ("job-alpha", "job-beta"):
        job_names = {path.name for path in (tmp_path / job_id).iterdir()}
        assert job_names == CYCLE_OUTPUT_NAMES
        assert "launch_draft_pack.json" not in job_names
        assert "site_draft_pack.json" not in job_names
        packet = json.loads((tmp_path / job_id / "commerce_operations_cycle_report.json").read_text(encoding="utf8"))
        projection = json.loads((tmp_path / job_id / "client_safe_projection.json").read_text(encoding="utf8"))
        assert packet["artifacts_written"] is True
        assert projection == packet["client_safe_projection"]
        assert "fingerprint" not in packet
        assert packet["report_version"] == "commerce-operations-cycle-v1"
    summary = json.loads((tmp_path / "batch_summary.json").read_text(encoding="utf8"))
    assert summary == printed
    assert summary["generated_at"] == "offline-deterministic"


@pytest.mark.parametrize(
    "name,expected_status",
    [
        ("raw_html_rejected.json", "blocked"),
        ("raw_payload_rejected.json", "blocked"),
        ("secret_like_token.json", "blocked"),
    ],
)
def test_html_token_and_raw_payload_jobs_are_blocked(tmp_path, name, expected_status):
    manifest = tmp_path / "one_unsafe.json"
    manifest.write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "id": "job-unsafe",
                        "marketplace_trend_report": f"tests/fixtures/commerce_operations/{name}",
                        "supplier_feasibility_report": "tests/fixtures/commerce_operations/cli_batch/good_supplier.json",
                        "consumer_attention_report": "tests/fixtures/commerce_operations/cli_batch/good_consumer.json",
                    }
                ]
            }
        ),
        encoding="utf8",
    )
    result = run_cli("--manifest", str(manifest), "--json")
    assert result.returncode == 1
    _assert_no_secret_leak(_combined(result))
    job = json.loads(result.stdout)["jobs"][0]
    assert job["status"] == expected_status
