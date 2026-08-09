"""Tests for services.ecommerce_operator.report.render_commerce_experiment_markdown."""
from services.ecommerce_operator.report import render_commerce_experiment_markdown
from services.ecommerce_operator.schemas import ContributionProfitResult, LaunchReadiness, ScaleDecision


def test_renders_all_sections_when_provided():
    readiness = LaunchReadiness(ready=True, checklist={"has_product_validation": True})
    contribution = ContributionProfitResult(product_name="Widget", contribution_profit=50.0)
    decision = ScaleDecision(decision="scale_approved", decision_reason="strong margin", next_action="scale spend")

    md = render_commerce_experiment_markdown("Widget", readiness=readiness, contribution=contribution, decision=decision)

    assert "MarketOS E-commerce Validation Experiment" in md
    assert "Launch Readiness" in md
    assert "Contribution Profit" in md
    assert "Kill/Scale Decision" in md
    assert "scale_approved" in md


def test_renders_gracefully_when_sections_omitted():
    md = render_commerce_experiment_markdown("Widget")
    assert "Widget" in md
    assert "Launch Readiness" not in md
