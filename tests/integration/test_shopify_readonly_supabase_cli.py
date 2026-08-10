from scripts.import_shopify_readonly import main

def test_shopify_cli_dry_run_never_writes(capsys):
    assert main(["--fixture", "tests/fixtures/shopify_readonly/shopify_sample.json", "--supabase-dry-run", "--json"]) == 0
    assert '"written_event_ids": []' in capsys.readouterr().out
