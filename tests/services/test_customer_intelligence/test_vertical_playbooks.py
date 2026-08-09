"""Tests for services.customer_intelligence.vertical_playbooks.build_vertical_playbook."""
import pytest
from services.customer_intelligence.schemas import VERTICALS
from services.customer_intelligence.vertical_playbooks import build_vertical_playbook

_REQUIRED_NONEMPTY_FIELDS = (
    "buyer_profile", "pain_points", "high_value_triggers", "offer_angles",
    "lead_sources", "outreach_channels", "ad_angles", "landing_page_structure",
    "qualification_questions", "appointment_setting_logic", "monetization_model", "risks",
)


class TestAllVerticalsProduceCompletePlaybooks:
    @pytest.mark.parametrize("vertical", VERTICALS)
    def test_every_required_field_is_populated(self, vertical):
        playbook = build_vertical_playbook(vertical)
        for field_name in _REQUIRED_NONEMPTY_FIELDS:
            value = getattr(playbook, field_name)
            assert value, f"{vertical}.{field_name} is empty"

    def test_all_seven_verticals_are_covered(self):
        assert len(VERTICALS) == 7
        assert set(VERTICALS) == {
            "real_estate", "car_sales", "ecommerce_brand", "clinic_wellness",
            "home_services", "coaching_consulting", "luxury_products",
        }


class TestUnknownVerticalNeverRaises:
    def test_unknown_vertical_returns_empty_but_valid_playbook(self):
        playbook = build_vertical_playbook("not_a_real_vertical")
        assert playbook.vertical == "not_a_real_vertical"
        assert playbook.buyer_profile == {}
        assert playbook.pain_points == []


class TestPlaybookSerialization:
    def test_to_dict_round_trips_all_fields(self):
        playbook = build_vertical_playbook("real_estate")
        d = playbook.to_dict()
        assert d["vertical"] == "real_estate"
        assert d["pain_points"] == playbook.pain_points
