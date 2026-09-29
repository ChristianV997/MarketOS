import json
import subprocess
from pathlib import Path
import pytest

CLI_PATH = Path("scripts/import_competitor_evidence.py").resolve()

@pytest.fixture
def run_cli():
    def _run_cli(csv_path: str, candidate_id: str):
        cmd = ["python", str(CLI_PATH), "--csv", str(csv_path), "--candidate-id", candidate_id]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result
    return _run_cli

def test_cli_valid_input_and_explicit_zeros(run_cli, tmp_path):
    csv_content = """title,url,price,shipping_cost,currency
Product 1,http://example.com/1,10.50,5.00,USD
Product 2,http://example.com/2,,0.00,USD
Product 3,http://example.com/3,0.00,,USD
"""
    csv_file = tmp_path / "valid.csv"
    csv_file.write_text(csv_content)

    res = run_cli(csv_file, "cand-abc")
    assert res.returncode == 0
    data = json.loads(res.stdout)

    assert data["candidate_id"] == "cand-abc"
    assert data["evidence_mode"] == "manual"
    assert data["offer_count"] == 3

    offers = data["imported_offers"]
    # Check explicit zero
    assert offers[1]["price"] is None
    assert offers[1]["shipping_cost"] == 0.0
    assert offers[2]["price"] == 0.0
    assert offers[2]["shipping_cost"] is None

def test_cli_missing_candidate_id_fails(tmp_path):
    csv_file = tmp_path / "valid.csv"
    csv_file.write_text("title,url\nP1,http://example.com/1")

    cmd = ["python", str(CLI_PATH), "--csv", str(csv_file)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode != 0
    assert "required: --candidate-id" in res.stderr

def test_cli_empty_candidate_id_fails(run_cli, tmp_path):
    csv_file = tmp_path / "valid.csv"
    csv_file.write_text("title,url\nP1,http://example.com/1")

    res = run_cli(csv_file, "   ")
    assert res.returncode != 0
    assert "cannot be empty" in res.stderr

def test_cli_malformed_csv_returns_cleanly(run_cli, tmp_path):
    csv_file = tmp_path / "malformed.csv"
    # Not real CSV but import_csv safely parses it as bad dicts or raises.
    # The CLI catches exceptions and returns code 1
    csv_file.write_text("title,url\nP1,http://example.com/1\nbad_line_no_commas")

    res = run_cli(csv_file, "cand-abc")
    # Actually python's csv module handles 'bad_line_no_commas' without crashing (just puts it in the first col)
    # But it won't have a 'url' so it's skipped.
    assert res.returncode == 0

def test_cli_enforces_row_limit(run_cli, tmp_path, monkeypatch):
    # Mock the MAX_ROWS in the script for the test
    import scripts.import_competitor_evidence as cli_mod
    monkeypatch.setattr(cli_mod, "MAX_ROWS", 2)

    csv_content = """title,url
1,http://example.com/1
2,http://example.com/2
3,http://example.com/3
"""
    csv_file = tmp_path / "large.csv"
    csv_file.write_text(csv_content)

    # We must run it directly, not via subprocess, because of monkeypatch
    sys_args = ["import_competitor_evidence.py", "--csv", str(csv_file), "--candidate-id", "cand-x"]
    monkeypatch.setattr("sys.argv", sys_args)
    return_code = cli_mod.main()

    assert return_code == 1

def test_cli_enforces_byte_limit(run_cli, tmp_path, monkeypatch):
    import scripts.import_competitor_evidence as cli_mod
    monkeypatch.setattr(cli_mod, "MAX_FILE_BYTES", 10) # very small limit

    csv_file = tmp_path / "large.csv"
    csv_file.write_text("title,url\n1,http://example.com/1") # way more than 10 bytes

    sys_args = ["import_competitor_evidence.py", "--csv", str(csv_file), "--candidate-id", "cand-x"]
    monkeypatch.setattr("sys.argv", sys_args)
    return_code = cli_mod.main()

    assert return_code == 1
