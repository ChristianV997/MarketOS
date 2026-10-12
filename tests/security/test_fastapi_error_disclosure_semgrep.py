"""Contract checks for the FastAPI exception-disclosure Semgrep guard."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RULE_PATH = ROOT / "semgrep" / "ai-safety.yml"
FIXTURE_PATH = ROOT / "semgrep" / "ai-safety.py"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "ci.yml"
RULE_ID = "marketos-fastapi-raw-exception-detail"


def test_semgrep_policy_contains_narrow_exception_disclosure_rule() -> None:
    policy = RULE_PATH.read_text(encoding="utf-8")

    assert policy.count(f"id: {RULE_ID}") == 1
    assert "severity: WARNING" in policy
    assert "detail=$DETAIL" in policy
    assert "str($EXCEPTION)" in policy
    assert "repr($EXCEPTION)" in policy
    assert "pattern-regex" in policy
    assert '"api/**"' in policy
    assert '"backend/api.py"' in policy
    assert '"backend/sidecars/**"' in policy


def test_blocking_semgrep_job_loads_the_canonical_policy() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "semgrep scan --config semgrep/ai-safety.yml --json" in workflow
    assert "semgrep scan --config semgrep/ai-safety.yml --severity ERROR --error" in workflow


def test_semgrep_fixture_covers_positive_and_negative_contracts() -> None:
    fixture = FIXTURE_PATH.read_text(encoding="utf-8")

    assert fixture.count(f"ruleid: {RULE_ID}") == 6
    assert fixture.count(f"ok: {RULE_ID}") == 4
    assert "detail=str(exception)" in fixture
    assert "detail=repr(exception)" in fixture
    assert 'return {"error": str(exception)}' in fixture
    assert 'return {"detail": str(exception)}' in fixture
    assert 'return JSONResponse({"message": str(exception)}' in fixture
    assert 'detail="internal_error"' in fixture
    assert '"type": type(exception).__name__' in fixture
    assert 'logger.exception("request failed"' in fixture


def test_semgrep_cli_executes_fixture_when_available() -> None:
    semgrep = shutil.which("semgrep")
    if semgrep is None:
        # The hosted policy job installs Semgrep; local environments may not.
        return

    env = os.environ.copy()
    env["SEMGREP_SEND_METRICS"] = "off"
    result = subprocess.run(
        [
            semgrep,
            "--test",
            "--config",
            str(RULE_PATH),
            str(FIXTURE_PATH),
            "--disable-version-check",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, json.dumps(
        {"stdout": result.stdout[-4000:], "stderr": result.stderr[-4000:]}
    )
