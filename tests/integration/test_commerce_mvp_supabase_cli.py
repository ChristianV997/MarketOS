from scripts.run_commerce_mvp_slice import main

def test_commerce_cli_dry_run_never_writes(capsys):
    assert main(["--fixture", "tests/fixtures/commerce_mvp/public_signals.json", "--query", "portable espresso maker", "--supabase-dry-run", "--json"]) == 0
    assert '"written_event_ids": []' in capsys.readouterr().out
