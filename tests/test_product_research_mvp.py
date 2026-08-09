import pytest

from backend.commercial.product_research import run_product_research


def test_product_research_is_deterministic_and_provenance_labeled():
    result = run_product_research("Insulated bottle", "home", "MX", 499)
    assert result["dry_run"] is True
    assert result["provenance"]["market_data"] == "not_connected"
    assert result["recommendation"] == "investigate"
    assert result["next_actions"]


@pytest.mark.parametrize("kwargs", [{"dry_run": False}, {"read_only": False}])
def test_product_research_rejects_unsafe_modes(kwargs):
    with pytest.raises(PermissionError): run_product_research("x", **kwargs)
