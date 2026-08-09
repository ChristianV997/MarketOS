"""Tests for services.digital_products.report."""
import backend.core.persistence as pers
import pytest
from services.digital_products.plan import build_digital_product_plan
from services.digital_products.report import render_digital_product_markdown


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(pers, "STATE_DIR", str(tmp_path))


def test_renders_all_sections():
    plan, _ = build_digital_product_plan("Thing", price=99.0)
    md = render_digital_product_markdown(plan)
    assert "MarketOS Digital Product Launch Plan" in md
    assert "Launch Checklist" in md
    assert "Kill/Iterate/Scale Criteria" in md
    assert "DRY RUN" in md
