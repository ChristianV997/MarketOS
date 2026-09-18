import json
from pathlib import Path

import scripts.run_high_value_path_harness as harness


def test_fixture_unit_economics_is_deterministic_and_repeatable():
    first = harness.measure_unit_economics()
    second = harness.measure_unit_economics()
    assert first["status"] in {"measured_fixture", "skipped_kernel_present_unwired"}
    if first["status"] == "measured_fixture":
        assert first["rows"] == 2
        assert first["repeated_match"] is True
        assert first["output_fingerprint"] == second["output_fingerprint"]
        assert first["wall_ms"] is not None


def test_replay_fingerprint_does_not_drift():
    report = harness.measure_replay()
    assert report["status"] == "measured_fixture"
    assert report["repeated_match"] is True
    assert len(report["output_fingerprint"]) == 64


def test_harness_never_claims_live_actions():
    report = harness.run_harness()
    assert report["live_actions"] is False
    assert report["quality_gate"] == "not_this_script"
    assert report["schema"] == "MarketOS.HighValuePathHarness.v1"
    ids = {item["path_id"] for item in report["measurements"]}
    assert ids == set(harness.PATH_IDS)
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
