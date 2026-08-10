from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "scripts/vendor_capability_report.py", *args], cwd=ROOT, text=True, capture_output=True, check=True)


def test_report_cli_is_deterministic_and_read_only() -> None:
    first = _run("--stage", "mvp", "--json")
    second = _run("--stage", "mvp", "--json")
    assert first.stdout == second.stdout
    report = json.loads(first.stdout)
    assert report["network_calls"] is False
    assert report["mutated"] is False


def test_report_cli_markdown_and_explicit_artifact_output() -> None:
    assert "did not contact a provider" in _run("--capability", "video_ad_generation", "--markdown").stdout
    target = ROOT / "artifacts" / "test-vendor-capability-report.json"
    try:
        _run("--json", "--output", "artifacts/test-vendor-capability-report.json")
        assert json.loads(target.read_text(encoding="utf-8"))["network_calls"] is False
    finally:
        target.unlink(missing_ok=True)
