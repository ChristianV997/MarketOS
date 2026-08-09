from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def run_script(*args: str, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment.update({"MARKETOS_MVP_MODE": "1", "ALLOWED_ORIGINS": "https://example.test"})
    if extra_env:
        environment.update(extra_env)
    return subprocess.run([sys.executable, "scripts/mvp_readiness.py", *args], cwd=ROOT, env=environment, text=True, capture_output=True, check=True)


def test_readiness_cli_emits_deterministic_local_json() -> None:
    first = run_script("--json")
    second = run_script("--json")
    assert first.stdout == second.stdout
    report = json.loads(first.stdout)
    assert report["status"] == "ready"
    assert report["network_calls"] is False
    assert report["mutated"] is False


def test_readiness_cli_reports_live_flag_and_writes_only_explicit_artifact(tmp_path: Path) -> None:
    blocked = json.loads(run_script("--json", extra_env={"CAPITAL_POLICY_LIVE": "1"}).stdout)
    assert blocked["status"] == "blocked"
    target = ROOT / "artifacts" / "test-mvp-readiness.json"
    try:
        completed = run_script("--json", "--output", "artifacts/test-mvp-readiness.json")
        assert json.loads(target.read_text(encoding="utf-8"))["status"] == "ready"
        assert completed.returncode == 0
    finally:
        target.unlink(missing_ok=True)


def test_readiness_cli_markdown_has_safety_statement() -> None:
    output = run_script("--markdown").stdout
    assert "MarketOS MVP Island readiness" in output
    assert "did not contact a provider" in output
