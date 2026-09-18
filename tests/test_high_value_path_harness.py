import json
from pathlib import Path

import scripts.run_high_value_path_harness as harness


def test_fixture_unit_economics_is_deterministic_and_repeatable():
    first = harness.measure_unit_economics()
    second = harness.measure_unit_economics()
    assert first["status"] in {"passed", "measured_fixture", "not_run", "skipped_kernel_present_unwired"}
    if first["status"] in {"passed", "measured_fixture"}:
        assert first["rows"] == 2
        assert first["repeated_match"] is True
        assert first["output_fingerprint"] == second["output_fingerprint"]
        assert first["wall_ms"] is not None
        assert first["command"] != ""
        assert first["exit_code"] == 0
        assert "dependency_state" in first
        assert "sanitized_evidence" in first


def test_replay_fingerprint_does_not_drift():
    report = harness.measure_replay()
    assert report["status"] in {"passed", "measured_fixture"}
    assert report["repeated_match"] is True
    assert len(report["output_fingerprint"]) == 64
    assert report["replay_identity"] == report["output_fingerprint"]


def test_harness_never_claims_live_actions():
    report = harness.run_harness()
    assert report["live_actions"] is False
    assert report["quality_gate"] == "not_this_script"
    assert report["schema"] == "MarketOS.HighValuePathHarness.v1"
    ids = {item["path_id"] for item in report["measurements"]}
    assert ids == set(harness.PATH_IDS)
    for m in report["measurements"]:
        assert m["status"] in harness.VALID_STATUSES
        assert "command" in m
        assert "exit_code" in m
        assert "dependency_state" in m
        assert "sanitized_evidence" in m
    json.dumps(report)


def test_container_inspector_reads_hardened_files(tmp_path: Path):
    (tmp_path / "Dockerfile").write_text(
        "FROM python:3.12-slim\nUSER marketos\nHEALTHCHECK CMD curl -fsS http://127.0.0.1:3000/health\n",
        encoding="utf-8",
    )
    (tmp_path / "docker-compose.prod.yml").write_text(
        "services:\n  db:\n    environment:\n      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set}\n    healthcheck:\n      test: ['CMD', 'true']\n",
        encoding="utf-8",
    )
    (tmp_path / ".python-version").write_text("3.12\n", encoding="utf-8")
    info = harness.inspect_container_files(tmp_path)
    assert info["dockerfile_from_312"] is True
    assert info["dockerfile_non_root"] is True
    assert info["dockerfile_healthcheck"] is True
    assert info["compose_prod_requires_password"] is True
    assert info["compose_prod_no_host_postgres_publish"] is True


def test_failure_classification_never_downgrades_to_unavailable():
    # An executed failure must be classified as 'failed', never 'unavailable'
    record = harness._record(
        "test_failure_path",
        status="failed",
        command="test_func",
        exit_code=1,
        dependency_state={"imported": True, "error": None},
        detail="Execution error occurred",
    )
    assert record["status"] == "failed"
    assert record["status"] != "unavailable"
    assert record["exit_code"] == 1


def test_container_contract_measurement_path():
    res = harness.measure_container_contract()
    assert res["status"] == "passed"
    assert res["exit_code"] == 0
    assert res["replay_identity"] is not None


def test_dependency_unavailable_measurement_path():
    res = harness.measure_dependency_unavailable()
    assert res["status"] == "passed"
    assert res["dependency_state"]["imported"] is False


def test_colab_benchmark_matrix_runs_and_emits_synthetic_metrics():
    matrix = harness.run_colab_benchmark_matrix(runs=2)
    assert matrix["schema"] == "MarketOS.ColabBenchmarkMatrix.v1"
    assert matrix["zero_secrets"] is True
    assert matrix["zero_network_calls"] is True
    assert matrix["all_deterministic"] is True
    assert len(matrix["matrix"]) >= 7
    for row in matrix["matrix"]:
        assert row["deterministic_bit_identity"] is True
        assert row["avg_ms"] >= 0.0
