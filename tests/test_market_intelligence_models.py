from backend.commercial_intelligence.market_models import MarketAttractivenessReport, MarketSignalSummary


def test_market_report_serializes_with_limits():
    summary=MarketSignalSummary("s","default","cat",demand_score=120,evidence_confidence=2)
    report=MarketAttractivenessReport("r","default","cat","Market",120,2,signal_summary=summary,missing_evidence=["thin evidence"])
    assert report.attractiveness_score == 100 and report.confidence_score == 1
    assert "limitations" in report.to_markdown().lower()
    assert MarketAttractivenessReport.from_dict(report.to_dict()).signal_summary.summary_id == "s"
