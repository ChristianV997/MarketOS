import json
from pathlib import Path
from scripts.import_shopify_readonly import main

ROOT = Path(__file__).resolve().parents[2]


def test_script_json_and_explicit_jsonl_write(tmp_path, capsys):
    fixture = "tests/fixtures/shopify_readonly/shopify_sample.json"; output = tmp_path / "events.jsonl"
    assert main(["--fixture", fixture, "--write-jsonl", str(output), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["canonical_event_count"] == 16 and len(output.read_text().splitlines()) == 16
