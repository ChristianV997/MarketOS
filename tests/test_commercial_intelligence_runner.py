from backend.commercial_intelligence import intelligence_runner


def test_runner_returns_partial_without_inputs():
    result=intelligence_runner.run_commercial_intelligence_cycle(category_name=None,include_market=False,include_product=False)
    assert result["status"] == "partial"
