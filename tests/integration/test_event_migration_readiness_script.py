import json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def test_readiness_script_is_deterministic_and_writes_only_explicit_output(tmp_path):
    output=tmp_path/"report.json";command=[sys.executable,"scripts/event_migration_readiness.py","--fixtures","--output",str(output)]
    first=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,check=True);second=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,check=True)
    assert first.stdout==second.stdout and output.exists()
    report=json.loads(first.stdout);assert report["fixture_count"]==5
