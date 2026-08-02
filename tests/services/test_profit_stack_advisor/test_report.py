"""Tests for services.profit_stack_advisor.report.render_profit_stack_advisor_markdown."""
from services.profit_stack_advisor.report import render_profit_stack_advisor_markdown
from services.profit_stack_advisor.schemas import ProfitStackAdvisorResult


def test_renders_title_and_sections():
    result = ProfitStackAdvisorResult(
        business_name="Own Store", business_model="own_ecommerce",
        recommendation={"strategy_id": "own_ecommerce_low_cost", "status": "recommended"},
    )
    md = render_profit_stack_advisor_markdown(result)
    assert "MarketOS Profit Stack Advisor" in md
    assert "Recommended Stack" in md
    assert "Cost Comparison" in md
    assert "DRY RUN" in md
