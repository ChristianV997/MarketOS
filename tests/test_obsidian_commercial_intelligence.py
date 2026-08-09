def test_commercial_intelligence_obsidian_sync_skips_without_vault(monkeypatch):
    from backend.obsidian.sync import sync_market_intelligence_note
    from backend.commercial_intelligence.market_models import MarketAttractivenessReport
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH",raising=False)
    result=sync_market_intelligence_note(MarketAttractivenessReport("m","default","cat","Market"))
    assert result["status"] in {"skipped","warning"}
