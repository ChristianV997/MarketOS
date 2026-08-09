from backend.organization.commercial_report import CommercialReport
from backend.organization.portfolio_report import build_portfolio_report


def make(report_id, service, status, risks, recommendations, actions):
    return CommercialReport(report_id, "w", "p", "", service, "Report", "Supported summary", recommendations=recommendations, risk_flags=risks, next_actions=actions, status=status)


def test_empty_portfolio_is_valid():
    result = build_portfolio_report("w", [])
    assert result.report_ids == [] and result.metadata["status"] == "empty"
    assert "No reports" in result.summary


def test_portfolio_aggregates_deterministically_without_claims():
    result = build_portfolio_report("w", [make("b", "unit_economics", "completed", ["z", "a"], ["Validate"], ["Next"]), make("a", "product_research", "blocked", ["a", "z", "z"], ["Validate", "Check"], ["Next"])])
    assert result.service_counts == {"product_research": 1, "unit_economics": 1}
    assert result.status_counts == {"blocked": 1, "completed": 1}
    assert result.recurring_risk_flags[0] == {"flag": "z", "count": 3}
    assert result.top_recommendations == ["Validate", "Check"]
    assert "actual profitability" not in result.summary
    assert "Service counts" in result.to_markdown()
