import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_deployment_scripts_are_local_and_read_only():
    result = subprocess.run([sys.executable, "scripts/deployment_smoke_check.py", "--env-file", "deploy/mvp/.env.mvp.example", "--json"], cwd=ROOT, capture_output=True, text=True, check=True)
    report = json.loads(result.stdout)
    assert report["network_calls"] is False
    assert report["mutated"] is False
    assert next(item for item in report["checks"] if item["name"] == "default_off_gates")["status"] == "passed"
