from backend.commercial_intelligence.product_models import ProductPositioning, ProductViabilityReport


def test_product_report_has_failure_modes_and_hypothesis_language():
    report=ProductViabilityReport("r","default","Tool","Cat","Product",viability_score=110,confidence_score=2,failure_modes=["weak differentiation"],positioning=ProductPositioning("p","default","Tool","Cat",metadata={"hypothesis_only":True}))
    assert report.viability_score == 100 and report.confidence_score == 1
    assert "Failure modes" in report.to_markdown()
    assert report.positioning.metadata["hypothesis_only"]
