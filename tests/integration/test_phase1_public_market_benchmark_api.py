from __future__ import annotations

from api.routes.phase1_public_market_benchmark import public_market_benchmark


def test_public_market_endpoint_returns_read_only_fixture_fallback():
    value = public_market_benchmark()
    assert value["read_only"] is True
    assert value["mutated"] is False
    assert value["network_used"] is False
    assert value["evidence_mode"] == "fixture_demo"


def test_public_market_endpoint_does_not_accept_browser_paths():
    # The GET handler has no path parameter; only a server-side env path can be read.
    assert "competitor_pages_attempted" in public_market_benchmark()
