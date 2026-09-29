import json
from scripts.run_returns_evaluator import run_returns_evaluator

def test_cli_eligible_fixture():
    fixture = json.dumps({
        "item_category": "standard",
        "days_since_delivery": 10,
        "condition": "new",
        "evidence": {
            "receipt": {"id": "rcpt-1", "source": "email_system"}
        }
    })
    result = run_returns_evaluator(fixture)
    assert result.get("eligible") is True
    assert result.get("reason") == "eligible"
    assert result.get("missing_evidence") == ()

def test_cli_missing_evidence():
    fixture = json.dumps({
        "item_category": "standard",
        "days_since_delivery": 10,
        "condition": "new",
        "evidence": {}
    })
    result = run_returns_evaluator(fixture)
    assert result.get("eligible") is False
    assert result.get("reason") == "missing_required_evidence"
    assert "receipt_missing" in result.get("missing_evidence", [])

def test_cli_malformed_json():
    result = run_returns_evaluator("{ bad json")
    assert "error" in result
    assert "malformed" in result["error"]

def test_cli_invalid_schema():
    fixture = json.dumps({
        "item_category": "standard",
        "days_since_delivery": "not an int",
        "condition": "new"
    })
    result = run_returns_evaluator(fixture)
    assert "error" in result
    assert "invalid input schema" in result["error"]

def test_cli_input_size_limit():
    huge_fixture = "x" * (1024 * 101)  # slightly over 100KB limit
    result = run_returns_evaluator(huge_fixture)
    assert "error" in result
    assert "limit" in result["error"]

def test_cli_malformed_evidence():
    fixture = json.dumps({
        "item_category": "standard",
        "days_since_delivery": 10,
        "condition": "new",
        "evidence": {
            "receipt": {"id": "1"} # missing source
        }
    })
    result = run_returns_evaluator(fixture)
    assert "error" in result
    assert "invalid input schema" in result["error"]
