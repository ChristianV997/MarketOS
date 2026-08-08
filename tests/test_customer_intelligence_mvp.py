import pytest

from backend.commercial.customer_intelligence import run_customer_intelligence


def test_customer_intelligence_known_vertical():
    result = run_customer_intelligence("Local brand", "car_sales", "MX", "vehicles")
    assert result["icp"]["evidence_status"] == "hypothesis_only"
    assert result["segments"] and result["qualification_questions"]
    assert result["provenance"]["customer_data"] == "not_connected"


def test_customer_intelligence_rejects_unsafe_mode():
    with pytest.raises(PermissionError): run_customer_intelligence("x", dry_run=False)
