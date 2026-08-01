"""Tests for services.creative_growth.report.render_creative_growth_markdown."""
from services.creative_growth.report import render_creative_growth_markdown
from services.creative_growth.schemas import CreativeGrowthPlan


def test_renders_title_and_sections():
    plan = CreativeGrowthPlan(
        product_name="Widget", hooks=["Hook A"], angles=["curiosity"],
        hook_matrix=[{"hook": "Hook A", "angle": "curiosity", "product": "Widget"}],
    )
    md = render_creative_growth_markdown(plan)
    assert "MarketOS Creative Testing & UGC Growth System" in md
    assert "Hook x Angle Testing Matrix" in md
    assert "DRY RUN" in md
