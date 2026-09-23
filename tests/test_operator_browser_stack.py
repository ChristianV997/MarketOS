"""Lifecycle, redaction, and evidence-class tests for the browser harness."""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

import pytest

from scripts.ai.operator_browser_stack import (
    EVIDENCE_FIXTURE,
    EVIDENCE_LIVE,
    EVIDENCE_LOCAL_UI,
    StackSession,
    artifact_dir_is_safe,
    assert_not_live,
    classify_evidence,
    port_open,
    powershell_command,
    probe_stack,
    redact_report,
    redact_text,
    scenario_matrix,
    spawn_tracked,
)


def test_non_loopback_port_probe_is_closed():
    assert port_open("example.com", 80) is False
    assert port_open("127.0.0.1", 0) is False
    assert port_open("127.0.0.1", 70000) is False


def test_port_open_sees_a_real_listener():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    port = sock.getsockname()[1]
    try:
        assert port_open("127.0.0.1", port) is True
    finally:
        sock.close()


def test_spawn_and_cleanup_reaps_the_child():
    session = StackSession()
    pid = spawn_tracked(session, "sleep", [sys.executable, "-c", "import time; time.sleep(30)"], cwd=Path("."))
    assert pid > 0
    stopped = session.stop(timeout_s=3)
    assert stopped[0]["name"] == "sleep"
    assert session.stopped is True


def test_redaction_strips_secrets_and_user_paths():
    raw = "api_key=supersecret /home/operator/token sk_live_abc123 C:\\Users\\HP\\Documents\\secret"
    cleaned = redact_text(raw)
    assert "supersecret" not in cleaned
    assert "sk_live_abc123" not in cleaned
    assert "HP" not in cleaned or "[redacted]" in cleaned
    report = redact_report({"note": raw, "evidence_class": EVIDENCE_FIXTURE})
    assert "supersecret" not in json.dumps(report)


def test_evidence_never_upgrades_local_runs():
    assert classify_evidence(browser_executed=True, live_ui=False) == EVIDENCE_FIXTURE
    assert classify_evidence(browser_executed=True, live_ui=True) == EVIDENCE_LOCAL_UI
    with pytest.raises(ValueError):
        assert_not_live(EVIDENCE_LIVE)


def test_probe_rejects_public_hosts():
    probe = probe_stack("https://api.example/ready", "https://shop.example")
    assert probe.note == "rejected_non_loopback"
    assert probe.api_ready is False
    assert probe.evidence_class == EVIDENCE_LOCAL_UI


def test_scenario_matrix_is_get_only_and_not_live():
    rows = scenario_matrix()
    assert len(rows) == 5 * 8 * 4
    assert "/operator/consulting-research" in {row["route"] for row in rows}
    assert "/operator/marketing-strategy" in {row["route"] for row in rows}
    assert all(row["live_validated"] is False for row in rows)
    assert {row["evidence_class"] for row in rows} == {EVIDENCE_FIXTURE}
    assert all(row["allowed_methods"] == ["GET"] for row in rows)
    assert all(row["live_validated"] is False for row in rows)
    assert any(row["api_mode"] == "malformed" and row["expected_surface"] == "unavailable" for row in rows)


def test_artifact_dir_rejects_git_and_source():
    assert artifact_dir_is_safe(Path("/tmp/marketos-operator-browser-acceptance"))
    repo = Path(__file__).resolve().parents[1]
    assert artifact_dir_is_safe(repo / ".git") is False


def test_powershell_command_is_argv_not_a_shell_string():
    argv = powershell_command(Path("C:/MarketOS"), ["--browser", "none"])
    assert argv[1].endswith("run_operator_browser_acceptance.py")
    assert "--json" in argv
    assert all(isinstance(part, str) for part in argv)
