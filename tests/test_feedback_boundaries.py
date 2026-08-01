from scripts.ai.verify_feedback_boundaries import run_checks


def test_feedback_boundary_harness_passes_without_external_credentials():
    checks = run_checks()
    assert all(checks.values()), checks


def test_metrics_ingestion_exposes_per_source_status():
    import orchestrator.main as orchestrator

    orchestrator._campaign_artifacts.clear()
    result = orchestrator._run_metrics_ingestion()
    assert "sources" in result
    assert "shopify" in result["sources"]
    assert "meta" in result["sources"]
