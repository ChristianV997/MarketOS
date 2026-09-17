from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PS1 = ROOT / "scripts" / "operators" / "marketos_ai_session.ps1"
WRAPPER = ROOT / "scripts" / "ai" / "operator_context_snapshot.ps1"
PROTOCOL = ROOT / "docs" / "ai" / "AI_CHAT_OPERATING_PROTOCOL.md"


def test_session_script_exists_and_is_ps51():
    text = PS1.read_text(encoding="utf-8")
    assert "#requires -Version 5.1" in text
    assert text.count("{") == text.count("}")
    assert "ValidateSet" in text
    assert "snapshot" in text
    assert "readiness" in text
    assert "select-tests" in text
    assert "frontend-check" in text
    assert "backend-check" in text
    assert "final-check" in text


def test_powershell_rejects_injection_and_destruction():
    text = PS1.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "invoke-expression" not in lowered
    assert "iex " not in lowered
    assert "git add" not in lowered
    assert "git reset" not in lowered
    assert "git checkout" not in lowered
    assert "git clean" not in lowered
    assert "remove-item" not in lowered
    assert "invoke-webrequest" not in lowered
    assert "start-process" not in lowered
    assert "LiteralPath" in text
    assert "MARKETOS_CLASSIFICATION" in text
    assert "$script:LastSessionCode" in text
    assert "Invoke-MarketOSOperator.ps1" in text


def test_wrapper_stays_thin_and_safe():
    text = WRAPPER.read_text(encoding="utf-8")
    assert "operator_context_snapshot.py" in text
    assert "Invoke-Expression" not in text
    assert "LiteralPath" in text
    assert "exit $LASTEXITCODE" in text


def test_protocol_documents_worktree_and_authorities():
    text = PROTOCOL.read_text(encoding="utf-8")
    assert "MarketOS.AIContext.v1" in text
    assert "worktree add" in text
    assert "worktree remove --" in text
    assert "canonical dirty checkout" in text.lower() or "Canonical dirty checkout" in text
    assert "PR #246" in text
    assert "PR #230" in text
    assert "PR #213" in text
    assert "compaction" in text.lower()
    assert "git reset --hard" in text
    assert "/api/phase1/evidence-cockpit" in text


def _powershell() -> str | None:
    return shutil.which("powershell") or shutil.which("pwsh")


def test_powershell_rejects_unexpected_repository(tmp_path: Path):
    shell = _powershell()
    if not shell:
        return
    unexpected = tmp_path / "not-marketos"
    unexpected.mkdir()
    completed = subprocess.run(
        [
            shell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(PS1),
            "-Action",
            "snapshot",
            "-RepositoryPath",
            str(unexpected),
            "-NoGitHub",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
        shell=False,
    )
    assert completed.returncode == 2
    combined = (completed.stdout or "") + (completed.stderr or "")
    assert "unexpected repository path" in combined.lower() or "MARKETOS_CLASSIFICATION" in combined


def test_powershell_rejects_path_metacharacters():
    shell = _powershell()
    if not shell:
        return
    completed = subprocess.run(
        [
            shell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(PS1),
            "-Action",
            "snapshot",
            "-RepositoryPath",
            "C:\\Users\\HP\\Documents\\MarketOS; calc.exe",
            "-NoGitHub",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
        shell=False,
    )
    assert completed.returncode == 2


def test_powershell_unknown_action_is_nonzero():
    shell = _powershell()
    if not shell:
        return
    completed = subprocess.run(
        [
            shell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(PS1),
            "-Action",
            "deploy",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
        shell=False,
    )
    assert completed.returncode != 0
