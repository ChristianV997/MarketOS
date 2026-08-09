"""Tests for services.customer_intelligence.report."""
import backend.core.persistence as pers
import pytest
from services.customer_intelligence.report import render_customer_intelligence_markdown
from services.customer_intelligence.sprint import build_customer_intelligence_sprint


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(pers, "STATE_DIR", str(tmp_path))


def test_renders_title_and_vertical_playbook_section():
    result, _ = build_customer_intelligence_sprint("clinic", vertical="clinic_wellness")
    md = render_customer_intelligence_markdown(result)
    assert "MarketOS Customer Acquisition Intelligence Sprint" in md
    assert "Vertical Playbook: clinic_wellness" in md
    assert "DRY RUN" in md


def test_omits_vertical_section_when_none():
    result, _ = build_customer_intelligence_sprint("shop", vertical=None)
    md = render_customer_intelligence_markdown(result)
    assert "Vertical Playbook" not in md
