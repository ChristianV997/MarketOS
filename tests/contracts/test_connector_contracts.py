from backend.providers.connector_contracts import list_connector_contracts


def test_connector_contracts_declare_events_and_non_mutating_boundaries() -> None:
    contracts = list_connector_contracts()
    assert contracts
    assert all(item.canonical_events_emitted and item.required_fixtures for item in contracts)
    assert all("publish" in item.forbidden_actions and "spend" in item.forbidden_actions for item in contracts)
    assert {item.vendor_id for item in contracts} >= {"google_news_rss", "supabase", "shopify", "creatify", "pagefly", "tidio"}
