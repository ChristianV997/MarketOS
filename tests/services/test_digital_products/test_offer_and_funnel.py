"""Tests for services.digital_products.offer and .funnel."""
from services.digital_products.funnel import build_funnel_plan
from services.digital_products.offer import create_digital_offer


class TestCreateDigitalOffer:
    def test_creates_offer_with_given_fields(self):
        offer = create_digital_offer("My Course", product_type="course", target_customer="marketers", price=299.0)
        assert offer.offer_name == "My Course"
        assert offer.product_type == "course"
        assert offer.price == 299.0

    def test_negative_price_clamped_to_zero(self):
        offer = create_digital_offer("Freebie", price=-50.0)
        assert offer.price == 0.0


class TestBuildFunnelPlan:
    def test_lead_magnet_matches_product_type(self):
        course_offer = create_digital_offer("Course", product_type="course")
        template_offer = create_digital_offer("Template", product_type="template")
        assert "lesson" in build_funnel_plan(course_offer).lead_magnet
        assert "template" in build_funnel_plan(template_offer).lead_magnet

    def test_unknown_product_type_falls_back_to_generic_lead_magnet(self):
        offer = create_digital_offer("Thing", product_type="not_a_real_type")
        funnel = build_funnel_plan(offer)
        assert funnel.lead_magnet  # non-empty, generic fallback

    def test_funnel_has_sales_page_structure(self):
        offer = create_digital_offer("Thing")
        funnel = build_funnel_plan(offer)
        assert funnel.sales_page_structure
        assert funnel.funnel_steps
