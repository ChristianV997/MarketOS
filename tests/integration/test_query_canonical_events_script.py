from scripts.query_canonical_events import main

def test_query_cli_reads_fixture_without_writes(capsys):
    assert main(["--jsonl", "tests/fixtures/event_queries/mixed_canonical_events.jsonl", "--workspace-id", "demo", "--commerce-runs", "--json"]) == 0
    assert '"run_id": "run-1"' in capsys.readouterr().out
